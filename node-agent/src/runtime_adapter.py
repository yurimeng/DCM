"""
Runtime Adapter Layer - 统一推理引擎接口
基于 F16-Runtime-Adapter-Layer 规范
"""

import time
import logging
from enum import Enum
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)


class RuntimeType(str, Enum):
    """支持的推理引擎类型"""
    OLLAMA = "ollama"
    VLLM = "vllm"
    TRT = "trt"
    OPENAI = "openai"


class ExecutionResult:
    """执行结果"""
    def __init__(
        self,
        execution_id: str,
        job_id: str,
        slot_id: str,
        status: str = "completed",
        output: Optional[Dict] = None,
        usage: Optional[Dict] = None,
        metrics: Optional[Dict] = None,
        error: Optional[str] = None
    ):
        self.execution_id = execution_id
        self.job_id = job_id
        self.slot_id = slot_id
        self.status = status
        self.output = output or {}
        self.usage = usage or {}
        self.metrics = metrics or {}
        self.error = error
    
    def to_dict(self) -> Dict:
        return {
            "execution_id": self.execution_id,
            "job_id": self.job_id,
            "slot_id": self.slot_id,
            "status": self.status,
            "output": self.output,
            "usage": self.usage,
            "metrics": self.metrics,
            "error": self.error
        }


class RuntimeAdapter:
    """Runtime Adapter Layer - 统一推理引擎接口"""
    
    def __init__(self, backend: str = "ollama", base_url: Optional[str] = None):
        self.backend = RuntimeType(backend)
        self.base_url = base_url or self._get_default_url()
        self.timeout = 120
    
    def _get_default_url(self) -> str:
        """获取默认 URL"""
        urls = {
            RuntimeType.OLLAMA: "http://localhost:11434",
            RuntimeType.VLLM: "http://localhost:8000/v1",
            RuntimeType.TRT: "http://localhost:8001/v1",
            RuntimeType.OPENAI: "https://api.openai.com/v1",
        }
        return urls.get(self.backend, "http://localhost:11434")
    
    def execute(self, invoke: Dict) -> ExecutionResult:
        """执行推理请求
        
        Args:
            invoke: 标准化的执行请求 (来自 F16 规范)
            
        Returns:
            ExecutionResult: 标准化的执行结果
        """
        execution_id = invoke.get("execution_id", "")
        job_id = invoke.get("job_id", "")
        slot_id = invoke.get("slot_id", "")
        
        start_time = time.time()
        
        try:
            if self.backend == RuntimeType.OLLAMA:
                result = self._execute_ollama(invoke)
            elif self.backend in [RuntimeType.VLLM, RuntimeType.TRT, RuntimeType.OPENAI]:
                result = self._execute_openai(invoke)
            else:
                raise ValueError(f"Unsupported backend: {self.backend}")
            
            # 计算指标
            latency_ms = int((time.time() - start_time) * 1000)
            
            return ExecutionResult(
                execution_id=execution_id,
                job_id=job_id,
                slot_id=slot_id,
                status="completed",
                output=result["output"],
                usage=result["usage"],
                metrics={
                    "latency_ms": latency_ms,
                    "tokens_per_second": result["usage"].get("output_tokens", 0) / (latency_ms / 1000) if latency_ms > 0 else 0
                }
            )
            
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return ExecutionResult(
                execution_id=execution_id,
                job_id=job_id,
                slot_id=slot_id,
                status="failed",
                error=str(e)
            )
    
    def _execute_ollama(self, invoke: Dict) -> Dict:
        """执行 Ollama 推理"""
        model_info = invoke.get("model", {})
        model_name = model_info.get("name", "qwen2.5:7b")
        
        input_data = invoke.get("input", {})
        messages = input_data.get("messages", [])
        
        generation = invoke.get("generation", {})
        max_tokens = generation.get("max_tokens", 100)
        temperature = generation.get("temperature", 0.7)
        
        # 构建 Ollama 请求
        ollama_payload = {
            "model": model_name,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "stream": False
        }
        
        # 调用 Ollama
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=ollama_payload,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        
        # 标准化输出
        return {
            "output": {
                "type": "chat_completion",
                "text": data.get("message", {}).get("content", ""),
                "finish_reason": "stop"
            },
            "usage": {
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
            }
        }
    
    def _execute_openai(self, invoke: Dict) -> Dict:
        """执行 OpenAI 兼容接口 (vLLM/TRT/OpenAI)"""
        model_info = invoke.get("model", {})
        model_name = model_info.get("name", "qwen2.5:7b")
        
        input_data = invoke.get("input", {})
        messages = input_data.get("messages", [])
        
        generation = invoke.get("generation", {})
        max_tokens = generation.get("max_tokens", 100)
        temperature = generation.get("temperature", 0.7)
        top_p = generation.get("top_p", 0.9)
        
        # 构建 OpenAI 请求
        openai_payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        
        # 调用 OpenAI 兼容接口
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=openai_payload,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        
        # 标准化输出
        choices = data.get("choices", [{}])
        message = choices[0].get("message", {}) if choices else {}
        usage = data.get("usage", {})
        
        return {
            "output": {
                "type": "chat_completion",
                "text": message.get("content", ""),
                "finish_reason": choices[0].get("finish_reason", "stop") if choices else "stop"
            },
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }
        }
    
    def health_check(self) -> bool:
        """检查 Runtime 是否可用"""
        try:
            if self.backend == RuntimeType.OLLAMA:
                resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            else:
                resp = requests.get(f"{self.base_url}/models", timeout=5)
            return resp.status_code == 200
        except:
            return False


def create_runtime_adapter(runtime_config: Optional[Dict] = None) -> RuntimeAdapter:
    """工厂函数：创建 Runtime Adapter"""
    if runtime_config is None:
        return RuntimeAdapter(backend="ollama")
    
    backend = runtime_config.get("backend", "ollama")
    base_url = runtime_config.get("base_url")
    
    return RuntimeAdapter(backend=backend, base_url=base_url)
