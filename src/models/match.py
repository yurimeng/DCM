"""
Match Model - F3: 撮合引擎
来源: PRD 0.2 Section 4.3 & Function/F3
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class MatchCreate(BaseModel):
    """Match 创建参数（内部使用）"""
    job_id: str
    node_id: str
    locked_price: float


class Match(BaseModel):
    """Match 完整模型"""
    match_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    node_id: str
    locked_price: float  # 撮合瞬间锁定，不受后续价格变动影响
    matched_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 执行后填充
    result_hash: Optional[str] = None
    actual_latency_ms: Optional[int] = None
    
    # 验证状态
    verified: bool = False
    verification_layer: Optional[int] = None  # 1 或 2
    layer2_consistency: Optional[float] = None  # 相似度（Layer 2）
    
    # 结算状态
    settled: bool = False
    settled_at: Optional[datetime] = None
    
    # 失败重试相关
    retry_count: int = 0
    original_match_id: Optional[str] = None  # 重试时指向原始 Match


class MatchResponse(BaseModel):
    """Match API 响应（内部）"""
    match_id: str
    job_id: str
    node_id: str
    locked_price: float
    matched_at: datetime
