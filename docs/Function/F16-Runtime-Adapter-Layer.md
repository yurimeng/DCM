# Runtime Adapter Layer (RAL)

> 统一不同推理引擎接口的适配层

---

## 1. 定位与职责

```
Runtime Adapter Layer = 推理引擎抽象层
```

### 核心职责
- 统一不同推理引擎（Ollama, vLLM, TRT-LLM, OpenAI-compatible）的输入输出格式
- 将 Execution Controller 的执行请求转换为各 Runtime 特定的调用格式
- 将 Runtime 返回结果标准化

### 边界定义
```
Node Agent 做：
✅ Runtime 适配
✅ 输入标准化
✅ 输出标准化

Node Agent 不做：
❌ 模型选择（由 Matching 决定）
❌ 定价策略
❌ 全局路由
```

---

## 2. 架构位置

```
┌─────────────────────────────────────────┐
│              Node Agent                 │
├─────────────────────────────────────────┤
│ 1. Slot Manager                        │
│ 2. Job Scheduler (Worker)              │
│ 3. Execution Controller                 │
│ 4. Runtime Adapter Layer  ← 核心      │
│ 5. Resource Manager                     │
│ 6. Telemetry / Heartbeat               │
└───────────────┬─────────────────────────┘
                │
    ┌───────────┼───────────┐
    │           │           │
 Ollama       vLLM       TRT-LLM
```

---

## 3. 数据流

```
1. Execution Controller 发送标准 invoke
        ↓
2. Runtime Adapter Layer 选择 backend
        ↓
3. 转换为 Runtime 特定格式 (Ollama/vLLM/TRT)
        ↓
4. 调用本地 Runtime API
        ↓
5. 接收 Runtime 响应
        ↓
6. 标准化为统一 output 格式
        ↓
7. 返回给 Execution Controller
```

---

## 4. 输入标准 (Invoke Structure)

Node Agent 接收的标准化执行请求：

```json
{
  "execution_id": "exec_001",
  "job_id": "job_001",
  "slot_id": "slot_001",

  "model": {
    "name": "qwen3-8b",
    "family": "qwen",
    "context_window": 32768
  },

  "input": {
    "type": "chat_completion",
    "messages": [
      {
        "role": "system",
        "content": "You are a helpful assistant"
      },
      {
        "role": "user",
        "content": "Explain fog computing"
      }
    ],
    "prompt_raw": null
  },

  "generation": {
    "max_tokens": 512,
    "temperature": 0.7,
    "top_p": 0.9,
    "stream": false
  },

  "runtime": {
    "backend": "ollama",
    "api_style": "openai"
  }
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| execution_id | string | ✅ | 执行唯一标识 |
| job_id | string | ✅ | Job ID |
| slot_id | string | ✅ | Slot ID |
| model | object | ✅ | 模型信息 |
| model.name | string | ✅ | 模型名称 |
| model.family | string | ✅ | 模型家族 |
| input | object | ✅ | 输入内容 |
| input.type | string | ✅ | 输入类型 (chat_completion/text) |
| input.messages | array | ✅ | 对话消息 |
| generation | object | ✅ | 生成参数 |
| generation.max_tokens | int | ✅ | 最大输出 token |
| generation.temperature | float | ❌ | 温度参数 |
| runtime | object | ✅ | 运行时信息 |
| runtime.backend | string | ✅ | 后端类型 |

---

## 5. 输出标准 (Result Structure)

Runtime Adapter Layer 返回的标准化结果：

```json
{
  "execution_id": "exec_001",
  "job_id": "job_001",
  "slot_id": "slot_001",
  
  "status": "completed",
  
  "output": {
    "type": "chat_completion",
    "text": "Fog computing is a distributed computing paradigm...",
    "finish_reason": "stop"
  },
  
  "usage": {
    "input_tokens": 25,
    "output_tokens": 128,
    "total_tokens": 153
  },
  
  "metrics": {
    "latency_ms": 1250,
    "first_token_ms": 320,
    "tokens_per_second": 102.4
  },
  
  "error": null
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| execution_id | string | 执行唯一标识 |
| job_id | string | Job ID |
| status | string | 执行状态 (completed/failed) |
| output | object | 输出内容 |
| output.text | string | 生成的文本 |
| usage | object | Token 使用统计 |
| usage.input_tokens | int | 输入 token 数 |
| usage.output_tokens | int | 输出 token 数 |
| metrics | object | 执行指标 |
| metrics.latency_ms | int | 总延迟 (ms) |
| metrics.first_token_ms | int | 首 token 延迟 (ms) |
| error | object/null | 错误信息 |

---

## 6. 支持的 Backend

### 6.1 Ollama

```python
class OllamaAdapter:
    """Ollama Runtime 适配器"""
    
    BASE_URL = "http://localhost:11434"
    
    # Ollama API 格式
    def to_ollama_request(self, invoke: dict) -> dict:
        return {
            "model": invoke["model"]["name"],
            "messages": invoke["input"]["messages"],
            "options": {
                "temperature": invoke["generation"].get("temperature", 0.7),
                "num_predict": invoke["generation"]["max_tokens"],
            },
            "stream": False
        }
    
    def from_ollama_response(self, resp: dict) -> dict:
        return {
            "output": {
                "type": "chat_completion",
                "text": resp["message"]["content"],
                "finish_reason": "stop" if not resp.get("done_reason") else resp["done_reason"]
            },
            "usage": {
                "input_tokens": resp.get("prompt_eval_count", 0),
                "output_tokens": resp.get("eval_count", 0),
            },
            "metrics": {
                "latency_ms": resp.get("total_duration", 0) // 1_000_000,
                "tokens_per_second": resp.get("eval_count", 0) / (resp.get("eval_duration", 1) / 1_000_000_000)
            }
        }
```

### 6.2 vLLM

```python
class VLLMAdapter:
    """vLLM Runtime 适配器"""
    
    BASE_URL = "http://localhost:8000/v1"
    
    def to_vllm_request(self, invoke: dict) -> dict:
        return {
            "model": invoke["model"]["name"],
            "messages": invoke["input"]["messages"],
            "max_tokens": invoke["generation"]["max_tokens"],
            "temperature": invoke["generation"].get("temperature", 0.7),
            "top_p": invoke["generation"].get("top_p", 0.9),
        }
```

### 6.3 OpenAI Compatible

```python
class OpenAIAdapter:
    """OpenAI 兼容接口适配器"""
    
    def to_openai_request(self, invoke: dict) -> dict:
        return {
            "model": invoke["model"]["name"],
            "messages": invoke["input"]["messages"],
            "max_tokens": invoke["generation"]["max_tokens"],
        }
```

---

## 7. Runtime Adapter Layer 实现

```python
from typing import Optional, Dict, Any
from enum import Enum

class RuntimeType(str, Enum):
    OLLAMA = "ollama"
    VLLM = "vllm"
    TRT = "trt"
    OPENAI = "openai"


class RuntimeAdapterLayer:
    """Runtime Adapter Layer - 统一推理引擎接口"""
    
    def __init__(self):
        self.adapters = {
            RuntimeType.OLLAMA: OllamaAdapter(),
            RuntimeType.VLLM: VLLMAdapter(),
            RuntimeType.OPENAI: OpenAIAdapter(),
        }
    
    def execute(self, invoke: dict, timeout: int = 120) -> dict:
        """执行推理请求"""
        # 1. 确定 backend
        backend = invoke.get("runtime", {}).get("backend", "ollama")
        
        # 2. 获取适配器
        adapter = self.adapters.get(RuntimeType(backend))
        if not adapter:
            return self._error_result(invoke, f"Unsupported backend: {backend}")
        
        # 3. 转换请求格式
        request = adapter.to_runtime_request(invoke)
        
        # 4. 调用 Runtime
        try:
            response = self._call_runtime(adapter, request, timeout)
            
            # 5. 标准化输出
            result = adapter.from_runtime_response(response)
            result["execution_id"] = invoke["execution_id"]
            result["job_id"] = invoke["job_id"]
            result["slot_id"] = invoke["slot_id"]
            result["status"] = "completed"
            
            return result
            
        except Exception as e:
            return self._error_result(invoke, str(e))
    
    def _call_runtime(self, adapter, request: dict, timeout: int) -> dict:
        """调用具体 Runtime"""
        # Ollama 特殊处理
        if isinstance(adapter, OllamaAdapter):
            import requests
            resp = requests.post(
                f"{adapter.BASE_URL}/api/chat",
                json=request,
                timeout=timeout
            )
            return resp.json()
        
        # OpenAI 兼容接口
        resp = requests.post(
            f"{adapter.BASE_URL}/chat/completions",
            json=request,
            timeout=timeout,
            headers={"Authorization": f"Bearer {adapter.api_key}"}
        )
        return resp.json()
    
    def _error_result(self, invoke: dict, error: str) -> dict:
        """错误结果"""
        return {
            "execution_id": invoke.get("execution_id"),
            "job_id": invoke.get("job_id"),
            "slot_id": invoke.get("slot_id"),
            "status": "failed",
            "error": error,
            "output": None,
            "usage": None,
            "metrics": None
        }
```

---

## 8. 与其他组件关系

| 组件 | 方向 | 说明 |
|------|------|------|
| Execution Controller | → RAL | 发送 invoke 请求 |
| Resource Manager | ↔ RAL | 请求 GPU/Memory 资源 |
| Telemetry | ← RAL | 上报执行 metrics |
| Slot Manager | ← RAL | 通知 slot 释放 |

---

## 9. 错误处理

```python
class RuntimeError(Exception):
    """Runtime 执行错误"""
    pass

class ModelNotFoundError(RuntimeError):
    """模型未找到"""
    pass

class TimeoutError(RuntimeError):
    """执行超时"""
    pass

class BackendUnavailableError(RuntimeError):
    """Backend 不可用"""
    pass
```

### 错误码

| 错误码 | 说明 |
|--------|------|
| RAL-001 | Backend 不支持 |
| RAL-002 | 模型加载失败 |
| RAL-003 | 执行超时 |
| RAL-004 | Runtime 连接失败 |
| RAL-005 | 输出解析失败 |

---

## 10. 配置

```yaml
runtime_adapter:
  default_backend: "ollama"
  timeout_seconds: 120
  
  backends:
    ollama:
      enabled: true
      base_url: "http://localhost:11434"
      
    vllm:
      enabled: false
      base_url: "http://localhost:8000/v1"
      
    trt:
      enabled: false
      base_url: "http://localhost:8001"
```

---

## 11. 监控指标

| 指标 | 类型 | 说明 |
|------|------|------|
| ral_executions_total | Counter | 总执行次数 |
| ral_execution_duration_seconds | Histogram | 执行延迟分布 |
| ral_errors_total | Counter | 错误次数 |
| ral_backend_requests | Counter | 各 backend 请求数 |

---

## 12. 一句话定义

> Runtime Adapter Layer 是 DCM Node Agent 的推理引擎抽象层，将标准化的执行请求转换为 Ollama/vLLM/TRT-LLM 等不同 Runtime 的特定格式，并标准化返回结果。
