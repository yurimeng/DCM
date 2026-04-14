"""
Job Model - DCM v3.2
Job = 需求单元 + Pre-Lock 状态支持

Job 配置 (DCM v3.2):
- max_output_tokens, max_input_tokens 等可从 job_config 读取
- messages 取代 prompt，支持上下文
"""

from enum import Enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
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


class Message(BaseModel):
    """消息结构 (DCM v3.2)
    
    取代原有的 prompt: str，支持多轮对话上下文
    
    Attributes:
        role: 角色类型 (system/user/assistant/tool)
        content: 消息内容
        name: 可选名称（如 tool name）
        metadata: 扩展信息
    """
    role: str = Field(..., description="角色: system/user/assistant/tool")
    content: str = Field(..., description="消息内容")
    name: Optional[str] = Field(None, description="可选名称")
    metadata: Optional[Dict[str, Any]] = Field(None, description="扩展信息")


class JobCreate(BaseModel):
    """Job 创建请求 (DCM v3.2)
    
    约束从 job_config 读取
    messages 取代 prompt，支持上下文
    """
    model_requirement: Optional[str] = Field(None, description="模型需求（可选）")
    input_tokens: int = Field(..., gt=0, description="输入 token 数量")
    output_tokens_limit: int = Field(..., gt=0, description="输出 token 上限")
    max_latency: int = Field(..., ge=1000, le=30000, description="最大延迟（ms）")
    bid_price: float = Field(..., gt=0, description="报价（USDC/1M tokens）")
    callback_url: Optional[str] = Field(None, description="异步回调 URL（可选）")
    region: Optional[str] = Field(None, description="区域偏好")
    
    # ===== messages 取代 prompt (DCM v3.2) =====
    messages: Optional[List[Message]] = Field(None, description="消息列表，支持上下文")
    prompt: Optional[str] = Field(None, description="兼容旧接口: 单个提示词")
    
    # ===== generation_params (DCM v3.2) =====
    generation_params: Optional[Dict[str, Any]] = Field(None, description="生成参数")
    
    @model_validator(mode='after')
    def validate_with_config(self) -> 'JobCreate':
        """使用 job_config 验证约束 (DCM v3.2)"""
        from ..services.job_config import get_job_config
        config = get_job_config()
        
        # 验证 output_tokens_limit
        if self.output_tokens_limit > config.max_output_tokens:
            raise ValueError(f"output_tokens_limit exceeds max_output_tokens ({config.max_output_tokens})")
        
        # 验证 input_tokens
        if self.input_tokens > config.max_input_tokens:
            raise ValueError(f"input_tokens exceeds max_input_tokens ({config.max_input_tokens})")
        
        # 验证 max_latency
        if self.max_latency > config.max_latency_ms:
            raise ValueError(f"max_latency exceeds max_latency_ms ({config.max_latency_ms})")
        
        if self.max_latency < config.min_latency_ms:
            raise ValueError(f"max_latency below min_latency_ms ({config.min_latency_ms})")
        
        # 验证 bid_price
        if self.bid_price > config.max_bid_price:
            raise ValueError(f"bid_price exceeds max_bid_price ({config.max_bid_price})")
        
        if self.bid_price < config.min_bid_price:
            raise ValueError(f"bid_price below min_bid_price ({config.min_bid_price})")
        
        return self
    
    def get_prompt_text(self) -> str:
        """获取纯文本 prompt (兼容)
        
        如果有 messages，返回最后一个 user message 的 content
        如果有 prompt，返回 prompt
        如果都没有，返回空字符串
        """
        if self.messages:
            # 找最后一个 user message
            for msg in reversed(self.messages):
                if msg.role == "user":
                    return msg.content
            # 没有 user message，返回最后一个 content
            if self.messages:
                return self.messages[-1].content
        return self.prompt or ""
    
    def get_messages_for_runtime(self) -> List[Dict[str, Any]]:
        """获取发送给 Runtime 的 messages
        
        优先使用 messages，否则从 prompt 构造
        """
        if self.messages:
            return [m.model_dump() for m in self.messages]
        elif self.prompt:
            # 从 prompt 构造一个 user message
            return [
                {
                    "role": "user",
                    "content": self.prompt,
                }
            ]
        return []


class Job(JobCreate):
    """Job 完整模型 (DCM v3.2)
    
    支持 Pre-Lock 机制:
    - cluster_id: 匹配的 Cluster
    - pre_lock_expires_at: Pre-Lock 过期时间
    - priority: 优先级
    """
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:8]}")
    status: JobStatus = Field(default=JobStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    matched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 匹配结果
    cluster_id: Optional[str] = Field(None, description="匹配的 Cluster ID")
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
    
    # Invoke 结构 (OpenAI 兼容)
    execution_id: Optional[str] = Field(None, description="执行ID")
    generation_params: Optional[dict] = Field(None, description="生成参数")
    runtime_info: Optional[dict] = Field(None, description="运行时信息")
    
    # ==================== 别名兼容 ====================
    @property
    def slot_id(self) -> Optional[str]:
        """兼容属性: cluster_id"""
        return self.cluster_id
    
    @slot_id.setter
    def slot_id(self, value: Optional[str]) -> None:
        """兼容设置: cluster_id"""
        self.cluster_id = value
    
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
