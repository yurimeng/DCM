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
    PENDING = "pending"     # 待锁定
    LOCKED = "locked"       # 已锁定，等待结算
    COMPLETED = "completed" # 已完成（等待转账）
    SETTLED = "settled"     # 已结算
    REFUNDED = "refunded"   # 已退款
    CANCELLED = "cancelled"  # 已取消


class Escrow(BaseModel):
    """Escrow 模型"""
    escrow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    match_id: Optional[str] = None
    
    # 金额（USDC）
    locked_amount: float  # 锁定金额 = bid_price × (input + output_limit) × 1.1 (bid_price: USDC/token)
    spent_amount: float = 0.0  # 已花费（实际结算）
    refund_amount: float = 0.0  # 退还金额
    
    status: EscrowStatus = Field(default=EscrowStatus.LOCKED)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 结算时间
    completed_at: Optional[datetime] = None  # Job 完成时间
    auto_complete_at: Optional[datetime] = None  # 计划自动完成时间
    settled_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    
    # 取消
    cancelled_by: Optional[str] = None  # 谁取消了
    cancel_reason: Optional[str] = None
    
    # 结算详情
    actual_tokens: Optional[int] = None
    actual_cost: Optional[float] = None
    platform_fee: Optional[float] = None
    node_earn: Optional[float] = None
    
    # 失败退款
    refund_reason: Optional[str] = None


class EscrowResponse(BaseModel):
    """Escrow API 响应"""
    escrow_id: str
    job_id: str
    locked_amount: float
    spent_amount: float
    refund_amount: float
    status: EscrowStatus
    created_at: datetime
    
    # 时间
    completed_at: Optional[datetime] = None
    auto_complete_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    
    # 结算详情
    actual_tokens: Optional[int] = None
    actual_cost: Optional[float] = None
    platform_fee: Optional[float] = None
    node_earn: Optional[float] = None
    
    # 取消
    cancelled_by: Optional[str] = None
    cancel_reason: Optional[str] = None


class EscrowCancelRequest(BaseModel):
    """取消 Escrow 请求"""
    reason: str = Field(..., description="取消原因")


class EscrowCompleteRequest(BaseModel):
    """手动完成 Escrow 请求"""
    pass


class SettlementRequest(BaseModel):
    """结算请求（内部）"""
    match_id: str
    actual_tokens: int
    locked_price: float
    verification_passed: bool
    is_mild_latency_penalty: bool = False  # 轻微延迟超标降价结算
    result_hash: Optional[str] = None  # 结果哈希（双账本同步用）
