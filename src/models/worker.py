"""
Worker Model - DCM v3.0
Worker = Job Queue + GPU 调度单元
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class WorkerStatus(str, Enum):
    """Worker 状态"""
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class Worker(BaseModel):
    """Worker 执行调度器
    
    Worker 是 Node 内的 GPU 调度单元，负责管理 Job Queue 和执行调度。
    """
    worker_id: str = Field(..., description="Worker ID")
    node_id: str = Field(..., description="所属节点 ID")
    gpu_id: int = Field(default=0, ge=0, description="GPU ID")
    
    # Queue 配置
    queue_size: int = Field(default=4, ge=1, description="Job 队列大小")
    current_queue: int = Field(default=0, ge=0, description="当前队列长度")
    
    # 状态
    status: WorkerStatus = Field(default=WorkerStatus.IDLE)
    
    # 运行时
    current_job_id: Optional[str] = Field(default=None, description="当前执行的 Job")
    
    # 元数据
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat: Optional[datetime] = None
    
    def is_available(self) -> bool:
        """检查 Worker 是否可用"""
        return (
            self.status == WorkerStatus.IDLE and
            self.current_queue < self.queue_size
        )
    
    def push_job(self, job_id: str) -> bool:
        """添加 Job 到队列"""
        if self.current_queue >= self.queue_size:
            return False
        
        self.current_queue += 1
        if self.status == WorkerStatus.IDLE:
            self.status = WorkerStatus.BUSY
        return True
    
    def pop_job(self) -> Optional[str]:
        """取出下一个 Job"""
        if self.current_queue <= 0:
            return None
        
        self.current_queue -= 1
        if self.current_queue == 0:
            self.status = WorkerStatus.IDLE
        return self.current_job_id
    
    def start_job(self, job_id: str) -> bool:
        """开始执行 Job"""
        if self.current_queue <= 0:
            return False
        
        self.current_job_id = job_id
        self.status = WorkerStatus.BUSY
        return True
    
    def complete_job(self) -> None:
        """完成 Job"""
        self.current_job_id = None
        if self.current_queue > 0:
            self.status = WorkerStatus.BUSY
        else:
            self.status = WorkerStatus.IDLE
    
    def get_load(self) -> float:
        """获取负载率"""
        if self.queue_size == 0:
            return 0.0
        return self.current_queue / self.queue_size


class WorkerResponse(BaseModel):
    """Worker API 响应"""
    worker_id: str
    node_id: str
    gpu_id: int
    status: WorkerStatus
    queue_size: int
    current_queue: int
    is_available: bool
