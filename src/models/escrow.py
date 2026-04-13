"""
Escrow Model - F6: 结算服务
来源: PRD 0.2 Section 5.5 & Function/F6
"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class EscrowStatus(str, Enum):
    """Escrow 状态"""
    LOCKED = "locked"      # 已锁定
    SETTLED = "settled"    # 已结算
    REFUNDED = "refunded"  # 已退款


class Escrow(BaseModel):
    """Escrow 模型"""
    escrow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    match_id: Optional[str] = None
    
    # 金额（USDC）
    locked_amount: float  # 锁定金额 = bid_price × (input + output_limit) / 1M × 1.1
    spent_amount: float = 0.0  # 已花费（实际结算）
    refund_amount: float = 0.0  # 退还金额
    
    status: EscrowStatus = Field(default=EscrowStatus.LOCKED)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    settled_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    
    # 结算详情
    actual_tokens: Optional[int] = None
    actual_cost: Optional[float] = None
    platform_fee: Optional[float] = None
    node_earn: Optional[float] = None
    
    # 失败退款
    refund_reason: Optional[str] = None


class EscrowResponse(BaseModel):
    """Escrow API 响应"""
    job_id: str
    locked_amount: float
    spent_amount: float
    refund_amount: float
    status: EscrowStatus
    
    # 结算后补充
    actual_tokens: Optional[int] = None
    actual_cost: Optional[float] = None
    platform_fee: Optional[float] = None
    node_earn: Optional[float] = None


class SettlementRequest(BaseModel):
    """结算请求（内部）"""
    match_id: str
    actual_tokens: int
    locked_price: float
    verification_passed: bool
    is_mild_latency_penalty: bool = False  # 轻微延迟超标降价结算
    result_hash: Optional[str] = None  # 结果哈希（双账本同步用）
