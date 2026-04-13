"""
Node Models - F2: 节点注册与状态管理
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
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
    region: str = Field(..., description="地理区域")
    
    @field_validator("model_support")
    @classmethod
    def validate_model_support(cls, v: List[str]) -> List[str]:
        # 支持 qwen2.5:7b
        allowed = ["qwen2.5:7b", "qwen3.5:latest", "gemma4:e4b", "llama3-8b"]
        for m in v:
            if m not in allowed:
                raise ValueError(f"Model {m} not supported")
        return v


class Node(BaseModel):
    """Node 完整信息"""
    node_id: str
    gpu_type: str
    vram_gb: int
    model_support: List[str]
    ask_price: float
    avg_latency: int
    region: str
    
    # 状态（运行时）
    status: NodeStatus = NodeStatus.OFFLINE
    stake_amount: float = 0.0
    stake_required: float = 0.0
    stake_tier: NodeTier = NodeTier.PERSONAL
    
    # 元数据
    registered_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    
    # 预留扩展字段（JSON 格式）
    # 未来可用于: 用户绑定、钱包地址、多个 Node_ID 等
    metadata: dict = Field(default_factory=dict)
    
    def get_stake_tier(self) -> NodeTier:
        """根据 GPU 数量确定等级"""
        # 简化：VRAM < 32GB 为 personal，32-64GB 为 professional，> 64GB 为 enterprise
        if self.vram_gb >= 64:
            return NodeTier.ENTERPRISE
        elif self.vram_gb >= 32:
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


class NodeResponse(BaseModel):
    """Node 响应"""
    node_id: str
    status: NodeStatus
    stake_required: float
    stake_amount: float
    next_step: str


class NodePollResponse(BaseModel):
    """Node 拉取 Job 响应"""
    has_job: bool
    job: Optional[dict] = None


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
