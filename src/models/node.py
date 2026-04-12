"""
Node Model - F2: 节点注册与状态管理
来源: PRD 0.2 Section 4.2 & Function/F2
"""

from enum import Enum
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
import uuid


class NodeStatus(str, Enum):
    """节点状态枚举"""
    ONLINE = "online"     # 可接受新 Job
    BUSY = "busy"        # 正在执行 Job，不接受新撮合
    OFFLINE = "offline"  # 未在线，无法接受 Job
    LOCKED = "locked"    # 争议冻结中，不接受新 Job


class NodeTier(str, Enum):
    """Stake 分级"""
    PERSONAL = "personal"      # < 24 GB, $50
    PROFESSIONAL = "professional"  # 24-80 GB, $200
    DATA_CENTER = "datacenter"  # > 80 GB, $1000


class NodeCreate(BaseModel):
    """Node 创建请求"""
    gpu_type: str = Field(..., description="GPU 类型（如 RTX4090, A100）")
    vram_gb: int = Field(..., gt=0, description="VRAM 大小（GB）")
    model_support: List[str] = Field(default=["llama3-8b"], description="支持的模型列表")
    ask_price: float = Field(..., gt=0, description="报价（USDC/1M tokens）")
    avg_latency: int = Field(..., gt=0, description="历史平均延迟（ms）")
    region: str = Field(..., description="地理区域")
    
    @field_validator("model_support")
    @classmethod
    def validate_model_support(cls, v: List[str]) -> List[str]:
        if "llama3-8b" not in v:
            raise ValueError("MVP 节点必须支持 llama3-8b 模型")
        return v


class Node(NodeCreate):
    """Node 完整模型"""
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: NodeStatus = Field(default=NodeStatus.OFFLINE)
    stake_amount: float = Field(default=0.0, description="已存入的 Stake（USDC）")
    stake_required: float = Field(default=0.0, description="需要存入的 Stake（USDC）")
    stake_tier: NodeTier = Field(default=NodeTier.PERSONAL)
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat: Optional[datetime] = None
    
    def __init__(self, **data):
        super().__init__(**data)
        # 自动计算 Stake 分级和门槛
        self._calculate_stake_tier()
    
    def _calculate_stake_tier(self):
        """根据 VRAM 计算 Stake 分级"""
        if self.vram_gb < 24:
            self.stake_tier = NodeTier.PERSONAL
            self.stake_required = 50.0
        elif self.vram_gb <= 80:
            self.stake_tier = NodeTier.PROFESSIONAL
            self.stake_required = 200.0
        else:
            self.stake_tier = NodeTier.DATA_CENTER
            self.stake_required = 1000.0


class NodePollResponse(BaseModel):
    """节点拉取 Job 响应"""
    has_job: bool
    job: Optional[dict] = None  # JobCreate 格式


class NodeResultSubmit(BaseModel):
    """节点提交执行结果"""
    result: str = Field(..., description="base64 编码的推理结果")
    result_hash: str = Field(..., description="结果的 SHA256 哈希")
    actual_latency_ms: int = Field(..., ge=0, description="实际执行延迟（ms）")
    actual_output_tokens: int = Field(..., ge=0, description="实际输出 token 数")


class NodeResponse(BaseModel):
    """Node API 响应"""
    node_id: str
    status: NodeStatus
    stake_required: float
    stake_amount: float
    next_step: str
