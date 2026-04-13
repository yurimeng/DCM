"""
Job Model - F1: Job 提交与管理系统
来源: PRD 0.2 Section 4.1 & Function/F1
"""

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import uuid


class JobStatus(str, Enum):
    """Job 状态枚举"""
    PENDING = "pending"      # 已提交，等待撮合
    MATCHED = "matched"      # 已撮合，节点正在执行
    RUNNING = "running"      # 节点已开始执行（可选中间态）
    COMPLETED = "completed"  # 执行成功，验证通过
    FAILED = "failed"        # 执行失败


class JobCreate(BaseModel):
    """Job 创建请求
    
    model: 可选，不指定则表示通用任务，系统选择最优模型
    """
    model: Optional[str] = Field(None, description="模型名称（可选，不指定则通用任务）")
    input_tokens: int = Field(..., gt=0, description="输入 token 数量")
    output_tokens_limit: int = Field(..., gt=0, le=4096, description="输出 token 上限")
    max_latency: int = Field(..., ge=1000, le=30000, description="最大延迟（ms）")
    bid_price: float = Field(..., gt=0, description="报价（USDC/1M tokens）")
    callback_url: Optional[str] = Field(None, description="异步回调 URL（可选）")
    
    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        # MVP 支持 qwen2.5:7b
        allowed_models = ["qwen2.5:7b", "qwen3.5:latest", "gemma4:e4b", "llama3-8b"]
        if v not in allowed_models:
            raise ValueError(f"仅支持模型: {', '.join(allowed_models)}")
        return v


class Job(JobCreate):
    """Job 完整模型"""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = Field(default=JobStatus.PENDING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    matched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 执行结果（完成后填充）
    actual_output_tokens: Optional[int] = None
    final_price: Optional[float] = None
    result: Optional[str] = None  # base64 encoded
    
    # 重试相关
    retry_count: int = Field(default=0)
    max_retries: int = 2


class JobResponse(BaseModel):
    """Job API 响应"""
    job_id: str
    escrow_amount: float  # 自动计算
    status: JobStatus
    created_at: datetime
    
    # 可选字段（状态相关）
    result: Optional[str] = None
    actual_output_tokens: Optional[int] = None
    final_price: Optional[float] = None
    matched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobQuery(BaseModel):
    """Job 查询参数"""
    status: Optional[JobStatus] = None
    limit: int = Field(default=100, le=1000)
    offset: int = Field(default=0, ge=0)
