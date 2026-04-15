"""
Runtime Protocol - DCM v3.2
Runtime 输入/输出标准化

统一 DCM 的 Runtime 调用接口，支持多种推理后端：
- Ollama
- vLLM
- llama.cpp
- transformers

Model 字段说明:
- model: Dict[str, Any] - 包含 name, family, context_window 等元数据
- 兼容字符串格式 (旧格式)，自动转换
"""

from typing import Optional, List, Dict, Any, Iterator, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from abc import ABC, abstractmethod


# ===== Request/Response 结构 =====

@dataclass
class Message:
    """消息结构"""
    role: str  # system, user, assistant
    content: str
    name: Optional[str] = None


@dataclass
class GenerationParams:
    """生成参数"""
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 500
    stop: Optional[List[str]] = None
    stream: bool = False


@dataclass
class RuntimeLimits:
    """调度限制 (DCM 特有)"""
    input_tokens: int = 0
    output_tokens_limit: int = 500
    max_latency_ms: int = 5000


@dataclass
class TokenUsage:
    """Token 使用量"""
    input_tokens: int = 0
    output_tokens: int = 0
    
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class RuntimeRequest:
    """
    Runtime 请求结构 (DCM v3.2)
    
    DCM Job 执行时发送给 Node Runtime 的标准化请求
    
    Model 字段: Union[Dict, str]
    - Dict 格式: {"name": "qwen2.5:7b", "family": "qwen", "context_window": 32768}
    - String 格式: "qwen2.5:7b" (兼容旧格式)
    """
    execution_id: str
    job_id: str
    model: Union[Dict[str, Any], str]  # Dict 或 String (DCM v3.2)
    messages: List[Message]
    generation: GenerationParams = field(default_factory=GenerationParams)
    limits: RuntimeLimits = field(default_factory=RuntimeLimits)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_model_name(self) -> str:
        """获取模型名称 (兼容处理)"""
        if isinstance(self.model, dict):
            return self.model.get("name", "qwen2.5:7b")
        elif isinstance(self.model, str):
            return self.model
        return "qwen2.5:7b"
    
    def get_model_family(self) -> str:
        """获取模型家族 (兼容处理)"""
        if isinstance(self.model, dict):
            family = self.model.get("family", "")
            if not family:
                name = self.model.get("name", "qwen2.5:7b")
                family = name.split(":")[0] if ":" in name else name
            return family
        elif isinstance(self.model, str):
            return self.model.split(":")[0] if ":" in self.model else self.model
        return "qwen2.5:7b"
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "job_id": self.job_id,
            "model": self.model,  # 保持原始格式
            "messages": [
                {"role": m.role, "content": m.content, "name": m.name}
                for m in self.messages
            ],
            "generation": asdict(self.generation),
            "limits": asdict(self.limits),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_job(
        cls,
        job_id: str,
        execution_id: str,
        model: str,
        messages: List[Message],
        generation_params: Optional[Dict] = None,
        job_limits: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> "RuntimeRequest":
        """从 Job 创建 RuntimeRequest"""
        generation = GenerationParams(**(generation_params or {}))
        limits = RuntimeLimits(**(job_limits or {}))
        
        return cls(
            execution_id=execution_id,
            job_id=job_id,
            model=model,
            messages=messages,
            generation=generation,
            limits=limits,
            metadata=metadata or {},
        )


class RuntimeStatus(str, Enum):
    """Runtime 执行状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class RuntimeResponse:
    """
    Runtime 响应结构
    
    Node Runtime 执行完成后返回的标准化响应
    """
    execution_id: str
    status: RuntimeStatus
    output: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success(self) -> bool:
        return self.status == RuntimeStatus.COMPLETED
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "status": self.status.value,
            "output": self.output,
            "usage": asdict(self.usage),
            "latency_ms": self.latency_ms,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class StreamChunk:
    """流式输出块"""
    execution_id: str
    delta: str  # 增量输出
    index: int = 0


# ===== Runtime Adapter =====

class RuntimeAdapter(ABC):
    """
    Runtime 适配器基类
    
    负责将 RuntimeRequest 转换为具体 Runtime 的格式
    并将响应转换回 RuntimeResponse
    """
    
    RUNTIME_TYPE: str = "base"
    
    def __init__(self, base_url: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
    
    @abstractmethod
    def generate(self, request: RuntimeRequest) -> RuntimeResponse:
        """
        同步生成
        
        Args:
            request: RuntimeRequest
            
        Returns:
            RuntimeResponse
        """
        pass
    
    @abstractmethod
    def generate_stream(self, request: RuntimeRequest) -> Iterator[StreamChunk]:
        """
        流式生成
        
        Args:
            request: RuntimeRequest
            
        Yields:
            StreamChunk
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查 Runtime 是否可用"""
        pass
    
    @abstractmethod
    def list_models(self) -> List[str]:
        """列出可用模型"""
        pass
    
    def _create_response(
        self,
        execution_id: str,
        status: RuntimeStatus,
        output: str = "",
        usage: Optional[TokenUsage] = None,
        latency_ms: int = 0,
        error: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> RuntimeResponse:
        """创建标准响应"""
        return RuntimeResponse(
            execution_id=execution_id,
            status=status,
            output=output,
            usage=usage or TokenUsage(),
            latency_ms=latency_ms,
            error=error,
            metadata=metadata or {},
        )


class OllamaAdapter(RuntimeAdapter):
    """
    Ollama Runtime 适配器
    
    支持 Ollama API 格式
    """
    
    RUNTIME_TYPE = "ollama"
    
    def __init__(self, host: str = "localhost", port: int = 11434, timeout: int = 60):
        super().__init__(f"http://{host}:{port}", timeout)
        self.host = host
        self.port = port
        self.api_url = f"{self.base_url}/api"
    
    def _messages_to_prompt(self, messages: List[Message]) -> str:
        """将 messages 转换为 Ollama 的 prompt"""
        parts = []
        for msg in messages:
            if msg.role == "system":
                parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                parts.append(f"Assistant: {msg.content}")
        return "\n\n".join(parts)
    
    def generate(self, request: RuntimeRequest) -> RuntimeResponse:
        """Ollama 生成"""
        import requests
        import time
        
        start_time = time.time()
        
        # 构建 Ollama 格式
        # 使用兼容方法获取模型名称 (DCM v3.2)
        payload = {
            "model": request.get_model_name(),
            "prompt": self._messages_to_prompt(request.messages),
            "options": {
                "temperature": request.generation.temperature,
                "top_p": request.generation.top_p,
                "num_predict": request.generation.max_tokens,
            },
            "stream": False,
        }
        
        if request.generation.stop:
            payload["options"]["stop"] = request.generation.stop
        
        try:
            response = requests.post(
                f"{self.api_url}/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            # 解析 Ollama 响应
            output = data.get("response", "")
            
            # 计算 token
            prompt_eval_count = data.get("prompt_eval_count", 0)
            eval_count = data.get("eval_count", self._estimate_tokens(output))
            
            usage = TokenUsage(
                input_tokens=prompt_eval_count,
                output_tokens=eval_count,
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.COMPLETED,
                output=output,
                usage=usage,
                latency_ms=latency_ms,
            )
            
        except requests.exceptions.Timeout:
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.TIMEOUT,
                error="Request timeout",
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.FAILED,
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
    
    def generate_stream(self, request: RuntimeRequest) -> Iterator[StreamChunk]:
        """Ollama 流式生成"""
        import requests
        
        # 使用兼容方法获取模型名称 (DCM v3.2)
        payload = {
            "model": request.get_model_name(),
            "prompt": self._messages_to_prompt(request.messages),
            "options": {
                "temperature": request.generation.temperature,
                "top_p": request.generation.top_p,
                "num_predict": request.generation.max_tokens,
            },
            "stream": True,
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/generate",
                json=payload,
                stream=True,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            index = 0
            for line in response.iter_lines():
                if line:
                    import json
                    data = json.loads(line)
                    delta = data.get("response", "")
                    if delta:
                        yield StreamChunk(
                            execution_id=request.execution_id,
                            delta=delta,
                            index=index,
                        )
                        index += 1
                        
        except Exception as e:
            yield StreamChunk(
                execution_id=request.execution_id,
                delta=f"[Error: {str(e)}]",
                index=0,
            )
    
    def is_available(self) -> bool:
        """检查 Ollama 是否可用"""
        import requests
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def list_models(self) -> List[str]:
        """列出 Ollama 可用模型"""
        import requests
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [m.get("name", "") for m in data.get("models", [])]
        except:
            pass
        return []


class VLLMAdapter(RuntimeAdapter):
    """
    vLLM Runtime 适配器
    
    支持 vLLM OpenAI-compatible API 格式
    """
    
    RUNTIME_TYPE = "vllm"
    
    def __init__(self, host: str = "localhost", port: int = 8000, timeout: int = 60):
        super().__init__(f"http://{host}:{port}/v1", timeout)
        self.host = host
        self.port = port
        self.api_url = f"{self.base_url}/chat/completions"
    
    def generate(self, request: RuntimeRequest) -> RuntimeResponse:
        """vLLM 生成"""
        import requests
        import time
        
        start_time = time.time()
        
        # 构建 OpenAI Chat 格式
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
        ]
        
        payload = {
            "model": request.get_model_name(),  # 兼容处理 (DCM v3.2)
            "messages": messages,
            "temperature": request.generation.temperature,
            "max_tokens": request.generation.max_tokens,
            "stream": False,
        }
        
        if request.generation.top_p:
            payload["top_p"] = request.generation.top_p
        if request.generation.stop:
            payload["stop"] = request.generation.stop
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            # 解析 OpenAI 响应
            choice = data.get("choices", [{}])[0]
            output = choice.get("message", {}).get("content", "")
            
            usage_data = data.get("usage", {})
            usage = TokenUsage(
                input_tokens=usage_data.get("prompt_tokens", 0),
                output_tokens=usage_data.get("completion_tokens", 0),
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.COMPLETED,
                output=output,
                usage=usage,
                latency_ms=latency_ms,
            )
            
        except requests.exceptions.Timeout:
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.TIMEOUT,
                error="Request timeout",
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.FAILED,
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
    
    def generate_stream(self, request: RuntimeRequest) -> Iterator[StreamChunk]:
        """vLLM 流式生成"""
        import requests
        
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
        ]
        
        payload = {
            "model": request.get_model_name(),  # 兼容处理 (DCM v3.2)
            "messages": messages,
            "temperature": request.generation.temperature,
            "max_tokens": request.generation.max_tokens,
            "stream": True,
        }
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                stream=True,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            index = 0
            for line in response.iter_lines():
                if line and line.startswith(b"data: "):
                    import json
                    data_str = line[6:].decode()
                    if data_str == "[DONE]":
                        break
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield StreamChunk(
                            execution_id=request.execution_id,
                            delta=delta,
                            index=index,
                        )
                        index += 1
                        
        except Exception as e:
            yield StreamChunk(
                execution_id=request.execution_id,
                delta=f"[Error: {str(e)}]",
                index=0,
            )
    
    def is_available(self) -> bool:
        """检查 vLLM 是否可用"""
        import requests
        try:
            response = requests.get(f"{self.base_url}/models", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def list_models(self) -> List[str]:
        """列出 vLLM 可用模型"""
        import requests
        try:
            response = requests.get(f"{self.base_url}/models", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [m.get("id", "") for m in data.get("data", [])]
        except:
            pass
        return []


class LlamaCppAdapter(RuntimeAdapter):
    """
    llama.cpp Server 适配器
    
    支持 llama.cpp HTTP Server API 格式
    """
    
    RUNTIME_TYPE = "llama.cpp"
    
    def __init__(self, host: str = "localhost", port: int = 8080, timeout: int = 60):
        super().__init__(f"http://{host}:{port}", timeout)
        self.host = host
        self.port = port
        self.api_url = f"{self.base_url}/completion"
    
    def generate(self, request: RuntimeRequest) -> RuntimeResponse:
        """llama.cpp 生成"""
        import requests
        import time
        
        start_time = time.time()
        
        # 构建 prompt
        prompt = self._messages_to_prompt(request.messages)
        
        payload = {
            "prompt": prompt,
            "n_predict": request.generation.max_tokens,
            "temperature": request.generation.temperature,
            "top_p": request.generation.top_p,
            "stream": False,
        }
        
        if request.generation.stop:
            payload["stop"] = request.generation.stop
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            output = data.get("content", "")
            latency_ms = int((time.time() - start_time) * 1000)
            
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.COMPLETED,
                output=output,
                usage=TokenUsage(
                    input_tokens=self._estimate_tokens(prompt),
                    output_tokens=self._estimate_tokens(output),
                ),
                latency_ms=latency_ms,
            )
            
        except requests.exceptions.Timeout:
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.TIMEOUT,
                error="Request timeout",
                latency_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return self._create_response(
                execution_id=request.execution_id,
                status=RuntimeStatus.FAILED,
                error=str(e),
                latency_ms=int((time.time() - start_time) * 1000),
            )
    
    def generate_stream(self, request: RuntimeRequest) -> Iterator[StreamChunk]:
        """llama.cpp 流式生成"""
        import requests
        
        prompt = self._messages_to_prompt(request.messages)
        
        payload = {
            "prompt": prompt,
            "n_predict": request.generation.max_tokens,
            "temperature": request.generation.temperature,
            "top_p": request.generation.top_p,
            "stream": True,
        }
        
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                stream=True,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            index = 0
            for line in response.iter_lines():
                if line:
                    import json
                    data = json.loads(line)
                    delta = data.get("content", "")
                    if delta:
                        yield StreamChunk(
                            execution_id=request.execution_id,
                            delta=delta,
                            index=index,
                        )
                        index += 1
                        
        except Exception as e:
            yield StreamChunk(
                execution_id=request.execution_id,
                delta=f"[Error: {str(e)}]",
                index=0,
            )
    
    def _messages_to_prompt(self, messages: List[Message]) -> str:
        """将 messages 转换为 prompt"""
        parts = []
        for msg in messages:
            if msg.role == "system":
                parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                parts.append(f"Assistant: {msg.content}")
        return "\n\n".join(parts)
    
    def is_available(self) -> bool:
        """检查 llama.cpp 是否可用"""
        import requests
        try:
            response = requests.get(self.base_url, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def list_models(self) -> List[str]:
        """llama.cpp 不支持动态模型列表"""
        return []


# ===== 工厂函数 =====

def create_runtime_adapter(
    runtime_type: str,
    host: str = "localhost",
    port: int = 11434,
    timeout: int = 60,
) -> RuntimeAdapter:
    """
    创建 Runtime 适配器
    
    Args:
        runtime_type: 运行时类型 ("ollama", "vllm", "llama.cpp")
        host: 主机地址
        port: 端口
        timeout: 超时时间(秒)
        
    Returns:
        RuntimeAdapter 实例
        
    Raises:
        ValueError: 不支持的运行时类型
    """
    runtime_type = runtime_type.lower()
    
    if runtime_type in ("ollama", "ollama"):
        return OllamaAdapter(host, port, timeout)
    elif runtime_type in ("vllm", "vllm-server"):
        return VLLMAdapter(host, port, timeout)
    elif runtime_type in ("llama.cpp", "llama-cpp", "llamacpp"):
        return LlamaCppAdapter(host, port, timeout)
    else:
        raise ValueError(f"Unsupported runtime type: {runtime_type}")


# ===== 辅助函数 =====

def estimate_tokens(text: str) -> int:
    """估算 token 数量 (简单基于字符)"""
    # 简单估算: 1 token ≈ 4 字符
    return max(1, len(text) // 4)


# 保留别名
RuntimeAdapter._estimate_tokens = staticmethod(estimate_tokens)

# 为每个适配器添加估算方法
for cls in [OllamaAdapter, VLLMAdapter, LlamaCppAdapter]:
    cls._estimate_tokens = staticmethod(estimate_tokens)
