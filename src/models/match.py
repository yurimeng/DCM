"""
Match Model - DCM v3.0
Match = 匹配结果 + 执行链路
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class MatchCreate(BaseModel):
    """Match 创建参数"""
    job_id: str
    slot_id: str
    node_id: str
    worker_id: str
    locked_price: float


class Match(BaseModel):
    """Match 完整模型
    
    Match 包含完整的执行链路信息：
    Job → Slot → Node → Worker → Runtime → Model
    """
    match_id: str = Field(default_factory=lambda: f"match_{uuid.uuid4().hex[:8]}")
    
    # 核心关联
    job_id: str = Field(..., description="Job ID")
    slot_id: str = Field(..., description="Slot ID")
    node_id: str = Field(..., description="Node ID")
    worker_id: str = Field(..., description="Worker ID")
    
    # 定价
    locked_price: float = Field(..., description="锁定价格")
    matched_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 模型
    model: str = Field(..., description="实际使用的模型")
    
    # 执行结果
    result_hash: Optional[str] = None
    actual_latency_ms: Optional[int] = None
    
    # 验证
    verified: bool = False
    verification_layer: Optional[int] = None  # 1 或 2
    layer2_consistency: Optional[float] = None
    
    # 结算
    settled: bool = False
    settled_at: Optional[datetime] = None
    
    # 失败重试
    retry_count: int = 0
    original_match_id: Optional[str] = None


class MatchResponse(BaseModel):
    """Match API 响应"""
    match_id: str
    job_id: str
    slot_id: str
    node_id: str
    worker_id: str
    locked_price: float
    matched_at: datetime
    model: str
