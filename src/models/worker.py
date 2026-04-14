"""
Worker Model - DCM v3.2
Worker = GPU Process + Runtime Adapter + Job 执行器

层级关系:
Cluster → Node → Worker → Runtime Adapter (Ollama/vLLM/TensorRT)

核心特性:
1. Worker 是进程级别，每个 GPU 对应一个 Worker
2. Worker 通过 Runtime Adapter 调用实际的推理服务
3. Worker 支持多线程，max_concurrency 控制并发
4. max_concurrency = min(GPU算力上限, 显存上限, runtime限制)
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class WorkerStatus(str, Enum):
    """Worker 状态"""
    IDLE = "idle"           # 空闲，等待任务
    BUSY = "busy"          # 处理中
    OFFLINE = "offline"     # 离线
    ERROR = "error"         # 错误状态


class RuntimeType(str, Enum):
    """Runtime 类型"""
    OLLAMA = "ollama"
    VLLM = "vllm"
    TENSORRT = "tensorrt"
    LMSTUDIO = "lmstudio"
    OPENAI = "openai"


class Worker(BaseModel):
    """Worker 执行器 (DCM v3.2)
    
    Worker 是进程级别的执行单元：
    - 运行在 Node 上，对应一个 GPU
    - 通过 Runtime Adapter 调用推理服务
    - 支持多线程并发处理
    
    容量计算:
    max_concurrency = min(gpu_compute_limit, vram_limit, runtime_limit)
    """
    worker_id: str = Field(..., description="Worker ID")
    node_id: str = Field(..., description="所属节点 ID")
    cluster_id: str = Field(..., description="所属 Cluster ID")
    
    # GPU 信息
    gpu_id: int = Field(default=0, ge=0, description="GPU ID")
    gpu_type: str = Field(default="", description="GPU 类型 (RTX4090, A100...)")
    vram_gb: float = Field(default=0.0, description="VRAM 大小 (GB)")
    
    # Runtime 配置
    runtime_type: RuntimeType = Field(default=RuntimeType.OLLAMA, description="Runtime 类型")
    runtime_host: str = Field(default="localhost", description="Runtime 地址")
    runtime_port: int = Field(default=11434, description="Runtime 端口")
    
    # 并发限制 (DCM v3.2)
    # max_concurrency = min(gpu_compute_limit, vram_limit, runtime_limit)
    # 这些值从 Node 心跳数据中提取，不由 Worker 硬编码
    max_concurrency: int = Field(default=1, ge=1, description="最大并发数 (从心跳提取)")
    gpu_compute_limit: Optional[int] = Field(None, description="GPU算力上限 (从心跳提取)")
    vram_limit: Optional[int] = Field(None, description="显存上限 (从心跳提取)")
    runtime_limit: Optional[int] = Field(None, description="Runtime限制 (从心跳提取)")
    
    # 当前状态
    active_jobs: int = Field(default=0, ge=0, description="当前活跃 Job 数")
    queued_jobs: int = Field(default=0, ge=0, description="排队的 Job 数")
    status: WorkerStatus = Field(default=WorkerStatus.IDLE)
    
    # 当前执行
    current_job_id: Optional[str] = Field(default=None, description="当前执行的 Job")
    
    # 元数据
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat: Optional[datetime] = None
    
    @staticmethod
    def calculate_max_concurrency(
        gpu_compute_limit: Optional[int] = None,
        vram_limit: Optional[int] = None,
        runtime_limit: Optional[int] = None
    ) -> int:
        """计算最大并发数 (从心跳数据提取)
        
        max_concurrency = min(gpu_compute_limit, vram_limit, runtime_limit)
        
        注意: 这些值从 Node 心跳数据获取，不是硬编码
        
        Args:
            gpu_compute_limit: GPU算力上限 (从心跳提取)
            vram_limit: 显存上限 (从心跳提取)
            runtime_limit: Runtime限制 (从心跳提取)
            
        Returns:
            最大并发数
        """
        limits = []
        if gpu_compute_limit is not None:
            limits.append(gpu_compute_limit)
        if vram_limit is not None:
            limits.append(vram_limit)
        if runtime_limit is not None:
            limits.append(runtime_limit)
        
        if not limits:
            return 1
        
        return min(limits)
    
    def available_capacity(self) -> int:
        """可用并发容量"""
        return max(0, self.max_concurrency - self.active_jobs)
    
    def is_available(self) -> bool:
        """检查 Worker 是否可用"""
        return (
            self.status == WorkerStatus.IDLE and
            self.available_capacity() > 0
        )
    
    def can_accept_job(self) -> bool:
        """是否能接收新 Job"""
        return self.available_capacity() > 0
    
    def start_job(self, job_id: str, tokens: int) -> bool:
        """开始执行 Job
        
        Args:
            job_id: Job ID
            tokens: 需要的 token 数量
            
        Returns:
            是否成功
        """
        if not self.can_accept_job():
            return False
        
        self.active_jobs += 1
        self.current_job_id = job_id
        self.status = WorkerStatus.BUSY
        return True
    
    def complete_job(self) -> None:
        """完成 Job"""
        if self.active_jobs > 0:
            self.active_jobs -= 1
        self.current_job_id = None
        
        if self.active_jobs == 0:
            self.status = WorkerStatus.IDLE
    
    def fail_job(self) -> None:
        """Job 执行失败"""
        self.complete_job()
    
    def get_load(self) -> float:
        """获取负载率"""
        if self.max_concurrency == 0:
            return 0.0
        return self.active_jobs / self.max_concurrency
    
    def add_to_queue(self) -> bool:
        """加入队列"""
        if self.can_accept_job():
            self.queued_jobs += 1
            return True
        return False
    
    def remove_from_queue(self) -> None:
        """从队列移除"""
        if self.queued_jobs > 0:
            self.queued_jobs -= 1


class WorkerResponse(BaseModel):
    """Worker API 响应"""
    worker_id: str
    node_id: str
    cluster_id: str
    gpu_id: int
    gpu_type: str
    runtime_type: RuntimeType
    max_concurrency: int
    active_jobs: int
    status: WorkerStatus
    is_available: bool
    load: float
