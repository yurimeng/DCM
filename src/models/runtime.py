"""
Runtime Model - DCM v3.0
Runtime = 模型执行环境
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class RuntimeType(str, Enum):
    """推理引擎类型"""
    OLLAMA = "ollama"
    VLLM = "vllm"
    TENSORRT_LLM = "tensorrt-llm"
    HF_TRANSFORMERS = "hf-transformers"


class Runtime(BaseModel):
    """Runtime 推理引擎配置
    
    Runtime 是模型执行环境，支持多种推理引擎。
    """
    runtime_id: str = Field(..., description="Runtime ID")
    worker_id: str = Field(..., description="所属 Worker ID")
    
    # 引擎类型
    runtime_type: RuntimeType = Field(..., description="推理引擎类型")
    
    # 连接配置
    endpoint: str = Field(..., description="API 端点，如 localhost:8000")
    api_key: Optional[str] = Field(default=None, description="API Key（可选）")
    
    # 模型配置
    model_name: str = Field(..., description="模型名称")
    context_window: int = Field(default=4096, ge=1, description="上下文窗口大小")
    
    # 状态
    ready: bool = Field(default=False, description="是否就绪")
    loaded: bool = Field(default=False, description="模型是否已加载")
    
    def get_endpoint_url(self, path: str = "") -> str:
        """获取完整 URL"""
        base = self.endpoint.rstrip("/")
        return f"{base}/{path}" if path else base
    
    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        if not v:
            raise ValueError("Endpoint cannot be empty")
        return v


class RuntimeStatus(BaseModel):
    """Runtime 状态"""
    runtime_id: str
    runtime_type: RuntimeType
    ready: bool
    loaded: bool
    model_name: str
    context_window: int
    current_load: int = 0
    avg_latency_ms: int = 0
