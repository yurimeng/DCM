"""
Status Report Models - DCM v3.2

两种状态报告：
1. Node Capacity Report (低频/稳态) - 30-60秒
2. Node Live Status Report (高频/调度) - 2-5秒
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class NodeCapacityReport(BaseModel):
    """Node Capacity Report (低频/稳态)
    
    上报频率: 30-60 秒
    用途: 容量配置、模型加载、长期规划
    """
    type: str = "node_capacity_report"
    node_id: str = Field(..., description="Node ID")
    timestamp: int = Field(..., description="时间戳 (毫秒)")
    
    # Worker 容量信息
    capacity: dict = Field(..., description="容量信息")
    # {
    #   "workers_total": 2,
    #   "workers_active": 2,
    #   "max_concurrency_total": 4
    # }
    
    # Runtime 信息
    runtime: dict = Field(..., description="Runtime 信息")
    # {
    #   "type": "vllm",
    #   "loaded_models": ["qwen3-8b"]
    # }
    
    # 性能信息
    performance: dict = Field(..., description="性能信息")
    # {
    #   "max_token_throughput": 1200
    # }


class NodeLiveStatus(BaseModel):
    """Node Live Status Report (高频/调度)
    
    上报频率: 2-5 秒
    用途: 实时调度、容量计算、匹配决策
    """
    type: str = "node_live_status"
    node_id: str = Field(..., description="Node ID")
    timestamp: int = Field(..., description="时间戳 (毫秒)")
    
    # VRAM 状态
    status: dict = Field(..., description="状态信息")
    # {
    #   "vram_used_gb": 18,
    #   "vram_total_gb": 48
    # }
    
    # 实时容量
    capacity: dict = Field(..., description="实时容量")
    # {
    #   "max_concurrency_available": 2
    # }
    
    # 负载信息
    load: dict = Field(..., description="负载信息")
    # {
    #   "active_jobs": 2,
    #   "available_token_capacity": 800
    # }


class WorkerStatus(BaseModel):
    """Worker 状态 (从 Live Status 提取)
    
    用于 Match Engine 计算 max_concurrency
    """
    worker_id: str = Field(..., description="Worker ID")
    gpu_id: int = Field(default=0, ge=0, description="GPU ID")
    
    # 并发限制 (从 status report 提取)
    max_concurrency: int = Field(default=1, ge=1, description="最大并发数")
    gpu_compute_limit: Optional[int] = Field(None, description="GPU算力上限")
    vram_limit: Optional[int] = Field(None, description="显存上限")
    runtime_limit: Optional[int] = Field(None, description="Runtime限制")
    
    # 负载状态
    active_jobs: int = Field(default=0, ge=0, description="活跃 Job 数")
    is_available: bool = Field(default=True, description="是否可用")
