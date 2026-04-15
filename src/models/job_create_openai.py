"""
JobCreate OpenAI Compatible - DCM v3.2
兼容 OpenAI Chat Completions API 格式

设计原则:
1. OpenAI 兼容 - 标准 OpenAI 客户端可以直接使用
2. DCM 扩展 - DCM 特有字段使用默认值
3. 价格统一 - 所有价格使用 USDC per token
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, model_validator, field_validator
import uuid


class Message(BaseModel):
    """消息结构 (OpenAI 兼容)"""
    role: str = Field(..., description="角色: system, user, assistant, tool")
    content: str = Field(..., description="消息内容")
    name: Optional[str] = Field(None, description="可选名称")


class JobCreateOpenAI(BaseModel):
    """
    OpenAI Chat Completions 兼容的 Job 创建请求
    
    兼容 OpenAI 格式，DCM 特有字段使用默认值。
    
    价格说明:
    - 所有价格统一使用 USDC per token
    - 0.000001 USDC/token = 1 USDC/1M tokens
    
    示例请求:
    ```json
    // 标准 OpenAI 格式 (可直接使用)
    {
        "model": "qwen2.5:7b",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100,
        "temperature": 0.7
    }
    
    // 完整 DCM 格式
    {
        "model": "qwen2.5:7b",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100,
        "temperature": 0.7,
        "bid_price": 0.000001,
        "max_latency": 30000,
        "user": "user-123",
        "callback_url": "https://example.com/callback",
        "region": "us-west",
        "priority": 5
    }
    
    // 兼容旧格式 (prompt 替代 messages)
    {
        "prompt": "Hello!",
        "bid_price": 0.000001,
        "max_latency": 30000
    }
    ```
    """
    
    # ===== OpenAI 标准字段 =====
    model: Optional[str] = Field(None, description="模型名称 (如 qwen2.5:7b)")
    messages: Optional[List[Message]] = Field(None, description="消息列表")
    
    # OpenAI generation 参数
    max_tokens: Optional[int] = Field(
        default=100,
        ge=1,
        le=32000,
        description="最大输出 tokens (默认: 100)"
    )
    temperature: Optional[float] = Field(
        default=0.7,
        ge=0,
        le=2.0,
        description="采样温度 (默认: 0.7)"
    )
    top_p: Optional[float] = Field(
        default=1.0,
        ge=0,
        le=1.0,
        description="Nucleus 采样 (默认: 1.0)"
    )
    frequency_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="频率惩罚 (默认: 0.0)"
    )
    presence_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description="存在惩罚 (默认: 0.0)"
    )
    stream: Optional[bool] = Field(
        default=False,
        description="流式响应 (默认: False)"
    )
    user: Optional[str] = Field(
        default=None,
        description="用户标识"
    )
    
    # ===== DCM 特有字段 (有默认值，标准客户端可直接使用) =====
    # 价格: USDC per token (0.000001 = 1 USDC/1M tokens)
    bid_price: float = Field(
        default=0.000001,
        gt=0,
        description="出价 USDC per token (默认: 0.000001 = 1 USDC/1M tokens)"
    )
    # 最大延迟: 毫秒
    max_latency: int = Field(
        default=30000,
        ge=1000,
        le=60000,
        description="最大延迟 ms (默认: 30000)"
    )
    
    # DCM 可选字段
    callback_url: Optional[str] = Field(
        default=None,
        description="回调 URL (可选)"
    )
    region: Optional[str] = Field(
        default=None,
        description="区域偏好 (可选)"
    )
    priority: int = Field(
        default=0,
        ge=0,
        le=10,
        description="优先级 (0-10, 默认: 0)"
    )
    
    # ===== 兼容旧接口 =====
    prompt: Optional[str] = Field(
        default=None,
        description="兼容: 单一 prompt (可替代 messages)"
    )
    
    # ===== 内部计算字段 =====
    input_tokens: Optional[int] = Field(
        default=None,
        description="输入 tokens (自动计算)"
    )
    
    @model_validator(mode='after')
    def validate_and_transform(self) -> 'JobCreateOpenAI':
        """验证并转换数据"""
        # 如果有 prompt 但没有 messages，转换为 messages
        if self.prompt and not self.messages:
            self.messages = [Message(role="user", content=self.prompt)]
        
        # 如果既没有 messages 也没有 prompt，使用默认消息
        if not self.messages:
            self.messages = [Message(role="user", content="Hello")]
        
        # 计算 input_tokens (从 messages 内容粗略估计)
        if self.input_tokens is None:
            total_chars = sum(len(m.content) for m in self.messages)
            self.input_tokens = max(1, total_chars // 4)  # 至少 1 token
        
        # 设置默认值
        if not self.max_tokens:
            self.max_tokens = 100
        
        return self
    
    def to_job_create(self) -> Dict[str, Any]:
        """
        转换为内部 JobCreate 格式
        
        返回给 JobRepository.create() 使用
        """
        # 优先使用 prompt 字段，其次从 messages 获取
        prompt_text = self.prompt or self.get_prompt_text()
        
        return {
            "user_id": self.user or "anonymous",
            "model": self.model,
            "messages": [m.model_dump() for m in self.messages] if self.messages else None,
            "prompt": prompt_text,  # 确保 prompt 有值
            "input_tokens": self.input_tokens or 100,
            "output_tokens_limit": self.max_tokens or 100,
            "max_latency": self.max_latency,
            "bid_price": self.bid_price,
            "callback_url": self.callback_url,
            "region": self.region,
            "priority": self.priority,
            "generation_params": self.get_generation_params(),
        }
    
    def to_job(self) -> 'Job':
        """
        转换为内部 Job 对象
        
        直接创建 Job 实例
        """
        from .job import Job
        
        job_data = self.to_job_create()
        return Job(**job_data)
    
    def get_generation_params(self) -> Dict[str, Any]:
        """获取 generation 参数"""
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "stream": self.stream,
        }
    
    def get_prompt_text(self) -> str:
        """获取纯文本 prompt (兼容)"""
        if self.messages:
            for msg in reversed(self.messages):
                if msg.role == "user":
                    return msg.content
            if self.messages:
                return self.messages[-1].content
        return self.prompt or ""
    
    def get_messages_for_runtime(self) -> List[Dict[str, Any]]:
        """获取发送给 Runtime 的 messages"""
        if self.messages:
            return [m.model_dump() for m in self.messages]
        elif self.prompt:
            return [{"role": "user", "content": self.prompt}]
        return []


# 别名: OpenAI 兼容的 Message 类
ChatMessage = Message

__all__ = [
    "Message",
    "ChatMessage",
    "JobCreateOpenAI",
]
