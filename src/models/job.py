"""
Job Model - DCM v3.1
Job = 需求单元 + Pre-Lock 状态支持

Job 状态转换 (DCM v3.1):
created → pending → matched → pre_locked → reserved → dispatched → running → finished
                                                        ↓
                                                    failed/cancelled
"""

from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
import uuid


class JobStatus(str, Enum):
    """Job 状态 (DCM v3.1)
    
    完整状态转换:
    PENDING → MATCHED → PRE_LOCKED → RESERVED → DISPATCHED → RUNNING → COMPLETED
                    ↓                           ↓
                 CANCELLED                  FAILED
    """
    CREATED = "created"           # 已创建
    PENDING = "pending"           # 已提交，等待撮合
    MATCHED = "matched"            # 已匹配到 Slot
    PRE_LOCKED = "pre_locked"     # 预锁定中
    RESERVED = "reserved"         # 已预约
    DISPATCHED = "dispatched"      # 已分发到 Worker
    RUNNING = "running"           # 正在执行
    COMPLETED = "completed"       # 执行成功
    FAILED = "failed"             # 执行失败
    CANCELLED = "cancelled"       # 已取消


class ModelRequirement(BaseModel):
    """模型需求"""
    family: str = Field(..., description="模型家族，如 qwen")
    name: Optional[str] = Field(None, description="模型名（可选）")


class PricingBid(BaseModel):
    """出价"""
    max_input_price: float = Field(..., gt=0, description="最大输入价格")
    max_output_price: float = Field(..., gt=0, description="最大输出价格")


class JobConstraints(BaseModel):
    """Job 约束"""
    max_latency_ms: int = Field(..., ge=1000, le=30000, description="最大延迟（ms）")
    region: Optional[str] = Field(None, description="区域限制")
    min_success_rate: Optional[float] = Field(None, ge=0, le=1, description="最低成功率")


class JobCreate(BaseModel):
    """Job 创建请求"""
    model_requirement: Optional[str] = Field(None, description="模型需求（可选）")
    input_tokens: int = Field(..., gt=0, description="输入 token 数量")
    output_tokens_limit: int = Field(..., gt=0, le=4096, description="输出 token 上限")
    max_latency: int = Field(..., ge=1000, le=30000, description="最大延迟（ms）")
    bid_price: float = Field(..., gt=0, description="报价（USDC/1M tokens）")
    callback_url: Optional[str] = Field(None, description="异步回调 URL（可选）")
    region: Optional[str] = Field(None, description="区域偏好")
    
    @field_validator("model_requirement")
    @classmethod
    def validate_model(cls, v: str) -> Optional[str]:
        if v is None:
            return None
        return v


class Job(JobCreate):
    """Job 完整模型 (DCM v3.1)
    
    支持 Pre-Lock 机制:
    - slot_id: 匹配的 Slot
    - pre_lock_expires_at: Pre-Lock 过期时间
    - priority: 优先级
    """
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:8]}")
    status: JobStatus = Field(default=JobStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    matched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 匹配结果
    slot_id: Optional[str] = Field(None, description="匹配的 Slot ID")
    node_id: Optional[str] = Field(None, description="匹配的 Node ID")
    worker_id: Optional[str] = Field(None, description="匹配的 Worker ID")
    used_model: Optional[str] = Field(None, description="实际使用的模型")
    
    # Pre-Lock 信息 (DCM v3.1)
    pre_locked_at: Optional[datetime] = Field(None, description="预锁定时间")
    pre_lock_expires_at: Optional[datetime] = Field(None, description="预锁定过期时间")
    reserved_at: Optional[datetime] = Field(None, description="预约时间")
    dispatched_at: Optional[datetime] = Field(None, description="分发时间")
    
    # 执行结果
    actual_output_tokens: Optional[int] = None
    final_price: Optional[float] = None
    result: Optional[str] = None  # base64 encoded
    
    # 优先级 (DCM v3.1)
    priority: int = Field(default=0, ge=0, le=10, description="优先级 (0-10)")
    
    # 重试
    retry_count: int = Field(default=0)
    max_retries: int = 2
    
    def is_terminal(self) -> bool:
        """是否终止状态"""
        return self.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
    
    def can_retry(self) -> bool:
        """是否可以重试"""
        return self.retry_count < self.max_retries and self.status == JobStatus.FAILED
    
    @property
    def model(self) -> Optional[str]:
        """兼容属性: 返回 model_requirement"""
        return self.model_requirement
    
    def pre_lock_expired(self) -> bool:
        """Pre-Lock 是否过期"""
        if self.pre_lock_expires_at is None:
            return False
        return datetime.utcnow() > self.pre_lock_expires_at


class JobResponse(BaseModel):
    """Job API 响应"""
    job_id: str
    escrow_amount: float
    status: JobStatus
    created_at: datetime
    result: Optional[str] = None
    actual_output_tokens: Optional[int] = None
    final_price: Optional[float] = None
    matched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    slot_id: Optional[str] = None
    pre_lock_expires_at: Optional[datetime] = None


class JobQuery(BaseModel):
    """Job 查询参数"""
    status: Optional[JobStatus] = None
    limit: int = Field(default=100, le=1000)
    offset: int = Field(default=0, ge=0)
