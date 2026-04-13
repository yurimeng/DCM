"""
Node Models - DCM v3.0
Node = Slot 集合 + 资源调度器
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class NodeTier(str, Enum):
    """Node 等级"""
    PERSONAL = "personal"    # 个人 (< 4 GPU)
    PROFESSIONAL = "professional"  # 专业 (4-8 GPU)
    ENTERPRISE = "enterprise"  # 企业 (> 8 GPU)


class NodeStatus(str, Enum):
    """Node 状态"""
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    LOCKED = "locked"


class NodeCreate(BaseModel):
    """Node 创建请求"""
    gpu_type: str = Field(..., description="GPU 类型（如 RTX4090, A100）")
    vram_gb: int = Field(..., gt=0, description="VRAM 大小（GB）")
    model_support: List[str] = Field(default=["qwen2.5:7b"], description="支持的模型列表")
    ask_price: float = Field(..., gt=0, description="报价（USDC/1M tokens）")
    avg_latency: int = Field(..., gt=0, description="历史平均延迟（ms）")
    avg_success_rate: float = Field(default=0.95, ge=0, le=1, description="平均成功率 (0-1)")
    avg_quality_score: float = Field(default=0.9, ge=0, le=1, description="平均质量评分 (0-1)")
    region: str = Field(..., description="地理区域")
    gpu_count: int = Field(default=1, ge=1, description="GPU 数量")
    
    @field_validator("model_support")
    @classmethod
    def validate_model_support(cls, v: List[str]) -> List[str]:
        allowed = ["qwen2.5:7b", "qwen3.5:latest", "gemma4:e4b", "llama3-8b"]
        for m in v:
            if m not in allowed:
                raise ValueError(f"Model {m} not supported")
        return v


class Node(BaseModel):
    """Node 资源容器
    
    Node = Slot 集合 + 资源调度器
    包含多个 Slots 和 Workers
    """
    node_id: str
    
    # 资源信息
    gpu_type: str
    vram_gb: int
    gpu_count: int = Field(default=1, ge=1, description="GPU 数量")
    model_support: List[str] = []
    ask_price: float
    avg_latency: int
    avg_success_rate: float = 0.95
    avg_quality_score: float = 0.9
    region: str
    
    # Slot 和 Worker 引用（实际数据在其他地方）
    slot_ids: List[str] = Field(default_factory=list, description="Slot ID 列表")
    worker_ids: List[str] = Field(default_factory=list, description="Worker ID 列表")
    
    # 状态
    status: NodeStatus = NodeStatus.OFFLINE
    stake_amount: float = 0.0
    stake_required: float = 0.0
    stake_tier: NodeTier = NodeTier.PERSONAL
    
    # 元数据
    registered_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)
    
    def get_stake_tier(self) -> NodeTier:
        """根据 GPU 数量确定等级"""
        if self.gpu_count >= 8:
            return NodeTier.ENTERPRISE
        elif self.gpu_count >= 4:
            return NodeTier.PROFESSIONAL
        return NodeTier.PERSONAL
    
    def get_stake_required(self) -> float:
        """根据等级确定所需 Stake"""
        tier = self.get_stake_tier()
        if tier == NodeTier.ENTERPRISE:
            return 1000.0
        elif tier == NodeTier.PROFESSIONAL:
            return 500.0
        return 200.0
    
    def add_slot(self, slot_id: str) -> None:
        """添加 Slot"""
        if slot_id not in self.slot_ids:
            self.slot_ids.append(slot_id)
    
    def remove_slot(self, slot_id: str) -> None:
        """移除 Slot"""
        if slot_id in self.slot_ids:
            self.slot_ids.remove(slot_id)
    
    def add_worker(self, worker_id: str) -> None:
        """添加 Worker"""
        if worker_id not in self.worker_ids:
            self.worker_ids.append(worker_id)
    
    def remove_worker(self, worker_id: str) -> None:
        """移除 Worker"""
        if worker_id in self.worker_ids:
            self.worker_ids.remove(worker_id)
    
    def is_online(self) -> bool:
        """检查是否在线"""
        return self.status == NodeStatus.ONLINE


class NodeResponse(BaseModel):
    """Node API 响应"""
    node_id: str
    status: NodeStatus
    stake_required: float
    stake_amount: float
    gpu_count: int
    slot_count: int
    worker_count: int
    next_step: str


class NodeHeartbeat(BaseModel):
    """Node 心跳"""
    status: str = "online"
    current_jobs: int = 0


class NodeResultSubmit(BaseModel):
    """Node 提交结果"""
    result: str = Field(..., description="Base64 编码的推理结果")
    result_hash: str = Field(..., description="结果 SHA256 哈希")
    actual_latency_ms: int = Field(..., ge=0)
    actual_output_tokens: int = Field(..., ge=0)


class NodePollResponse(BaseModel):
    """Node 轮询响应"""
    has_job: bool
    job_id: Optional[str] = None
    match_id: Optional[str] = None
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens_limit: Optional[int] = None
    max_latency: Optional[int] = None
    locked_price: Optional[float] = None
    message: Optional[str] = None
