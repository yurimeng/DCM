"""
Runtime Protocol 测试 - DCM v3.2
"""

import pytest
from src.models.runtime_protocol import (
    Message,
    GenerationParams,
    RuntimeLimits,
    TokenUsage,
    RuntimeRequest,
    RuntimeResponse,
    RuntimeStatus,
    StreamChunk,
    RuntimeAdapter,
    OllamaAdapter,
    VLLMAdapter,
    LlamaCppAdapter,
    create_runtime_adapter,
    estimate_tokens,
)


class TestMessage:
    """Message 测试"""
    
    def test_create(self):
        """创建消息"""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.name is None
    
    def test_with_name(self):
        """创建带名字的消息"""
        msg = Message(role="assistant", content="Hi", name="AI")
        assert msg.name == "AI"


class TestGenerationParams:
    """GenerationParams 测试"""
    
    def test_defaults(self):
        """默认参数"""
        params = GenerationParams()
        assert params.temperature == 0.7
        assert params.top_p == 0.9
        assert params.max_tokens == 500
        assert params.stream is False
    
    def test_custom(self):
        """自定义参数"""
        params = GenerationParams(
            temperature=0.9,
            max_tokens=1000,
            stream=True,
        )
        assert params.temperature == 0.9
        assert params.max_tokens == 1000
        assert params.stream is True


class TestRuntimeLimits:
    """RuntimeLimits 测试"""
    
    def test_defaults(self):
        """默认限制"""
        limits = RuntimeLimits()
        assert limits.input_tokens == 0
        assert limits.output_tokens_limit == 500
        assert limits.max_latency_ms == 5000
    
    def test_custom(self):
        """自定义限制"""
        limits = RuntimeLimits(
            input_tokens=400,
            output_tokens_limit=500,
            max_latency_ms=2000,
        )
        assert limits.input_tokens == 400
        assert limits.output_tokens_limit == 500


class TestTokenUsage:
    """TokenUsage 测试"""
    
    def test_total(self):
        """总 token 数"""
        usage = TokenUsage(input_tokens=100, output_tokens=200)
        assert usage.total_tokens == 300
    
    def test_defaults(self):
        """默认值为 0"""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0


class TestRuntimeRequest:
    """RuntimeRequest 测试"""
    
    def test_create(self):
        """创建请求"""
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="What is AI?"),
        ]
        
        request = RuntimeRequest(
            execution_id="exe_001",
            job_id="job_001",
            model="qwen3-8b",
            messages=messages,
        )
        
        assert request.execution_id == "exe_001"
        assert request.job_id == "job_001"
        assert request.model == "qwen3-8b"
        assert len(request.messages) == 2
    
    def test_to_dict(self):
        """转换为字典"""
        request = RuntimeRequest(
            execution_id="exe_001",
            job_id="job_001",
            model="qwen3-8b",
            messages=[Message(role="user", content="Hi")],
        )
        
        data = request.to_dict()
        assert data["execution_id"] == "exe_001"
        assert data["model"] == "qwen3-8b"
        assert len(data["messages"]) == 1
    
    def test_from_job(self):
        """从 Job 创建"""
        messages = [Message(role="user", content="Hello")]
        
        request = RuntimeRequest.from_job(
            job_id="job_001",
            execution_id="exe_001",
            model="qwen3-8b",
            messages=messages,
            generation_params={"temperature": 0.8},
            job_limits={"output_tokens_limit": 1000},
        )
        
        assert request.generation.temperature == 0.8
        assert request.limits.output_tokens_limit == 1000


class TestRuntimeResponse:
    """RuntimeResponse 测试"""
    
    def test_success(self):
        """成功响应"""
        response = RuntimeResponse(
            execution_id="exe_001",
            status=RuntimeStatus.COMPLETED,
            output="Hello!",
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            latency_ms=100,
        )
        
        assert response.success is True
        assert response.status == RuntimeStatus.COMPLETED
    
    def test_failure(self):
        """失败响应"""
        response = RuntimeResponse(
            execution_id="exe_001",
            status=RuntimeStatus.FAILED,
            error="Connection timeout",
            latency_ms=100,
        )
        
        assert response.success is False
        assert response.error == "Connection timeout"
    
    def test_to_dict(self):
        """转换为字典"""
        response = RuntimeResponse(
            execution_id="exe_001",
            status=RuntimeStatus.COMPLETED,
            output="Hi",
        )
        
        data = response.to_dict()
        assert data["execution_id"] == "exe_001"
        assert data["status"] == "completed"


class TestRuntimeAdapter:
    """RuntimeAdapter 测试"""
    
    def test_factory_ollama(self):
        """创建 Ollama 适配器"""
        adapter = create_runtime_adapter("ollama", host="localhost", port=11434)
        assert isinstance(adapter, OllamaAdapter)
        assert adapter.host == "localhost"
        assert adapter.port == 11434
    
    def test_factory_vllm(self):
        """创建 vLLM 适配器"""
        adapter = create_runtime_adapter("vllm", host="localhost", port=8000)
        assert isinstance(adapter, VLLMAdapter)
        assert adapter.port == 8000
    
    def test_factory_llamacpp(self):
        """创建 llama.cpp 适配器"""
        adapter = create_runtime_adapter("llama.cpp", host="localhost", port=8080)
        assert isinstance(adapter, LlamaCppAdapter)
        assert adapter.port == 8080
    
    def test_factory_unsupported(self):
        """不支持的运行时"""
        with pytest.raises(ValueError):
            create_runtime_adapter("unknown_runtime")


class TestOllamaAdapter:
    """OllamaAdapter 测试"""
    
    def test_messages_to_prompt(self):
        """Messages 转 Prompt"""
        adapter = OllamaAdapter()
        
        messages = [
            Message(role="system", content="You are AI"),
            Message(role="user", content="Hello"),
        ]
        
        prompt = adapter._messages_to_prompt(messages)
        
        assert "System: You are AI" in prompt
        assert "User: Hello" in prompt
    
    def test_messages_with_assistant(self):
        """带 assistant 消息"""
        adapter = OllamaAdapter()
        
        messages = [
            Message(role="user", content="Hi"),
            Message(role="assistant", content="Hello!"),
            Message(role="user", content="How are you?"),
        ]
        
        prompt = adapter._messages_to_prompt(messages)
        
        assert "User: Hi" in prompt
        assert "Assistant: Hello!" in prompt
        assert "User: How are you?" in prompt


class TestLlamaCppAdapter:
    """LlamaCppAdapter 测试"""
    
    def test_messages_to_prompt(self):
        """Messages 转 Prompt"""
        adapter = LlamaCppAdapter()
        
        messages = [
            Message(role="system", content="You are AI"),
            Message(role="user", content="Hello"),
        ]
        
        prompt = adapter._messages_to_prompt(messages)
        
        assert "System: You are AI" in prompt
        assert "User: Hello" in prompt


class TestEstimateTokens:
    """Token 估算测试"""
    
    def test_basic(self):
        """基本估算"""
        # 约 4 字符 = 1 token
        text = "a" * 100
        tokens = estimate_tokens(text)
        assert 20 <= tokens <= 30  # 100/4 = 25
    
    def test_empty(self):
        """空文本"""
        assert estimate_tokens("") == 1
    
    def test_chinese(self):
        """中文估算"""
        # 中文每个字约 1-2 token
        text = "你好世界"
        tokens = estimate_tokens(text)
        assert tokens >= 1


class TestStreamChunk:
    """StreamChunk 测试"""
    
    def test_create(self):
        """创建流块"""
        chunk = StreamChunk(
            execution_id="exe_001",
            delta="Hello",
            index=0,
        )
        
        assert chunk.execution_id == "exe_001"
        assert chunk.delta == "Hello"
        assert chunk.index == 0


class TestRuntimeClient:
    """RuntimeClient 测试"""
    
    def test_create_with_ollama(self):
        """创建 Ollama Runtime 客户端"""
        from src.agents.node_agent import RuntimeClient, NodeConfig
        
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
            runtime_type="ollama",
            ollama_host="localhost",
            ollama_port=11434,
        )
        
        client = RuntimeClient(config)
        
        assert client._adapter is not None
        assert isinstance(client._adapter, OllamaAdapter)
    
    def test_create_with_vllm(self):
        """创建 vLLM Runtime 客户端"""
        from src.agents.node_agent import RuntimeClient, NodeConfig
        
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
            runtime_type="vllm",
            ollama_host="localhost",
            ollama_port=8000,
        )
        
        client = RuntimeClient(config)
        
        assert client._adapter is not None
        assert isinstance(client._adapter, VLLMAdapter)


class TestNodeAgentRuntime:
    """Node Agent Runtime 集成测试"""
    
    def test_runtime_client_initialized(self):
        """测试 Runtime 客户端已初始化"""
        from src.agents.node_agent import NodeAgent, NodeConfig
        from unittest.mock import patch
        
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
        )
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
        
        # 验证 runtime 客户端已初始化
        assert agent.runtime is not None
        # 检查 runtime 客户端有 _adapter 属性
        assert hasattr(agent.runtime, '_adapter')
        assert agent.runtime._adapter is not None


class TestRuntimeProtocolFlow:
    """Runtime Protocol 完整流程测试"""
    
    def test_request_to_response_flow(self):
        """测试从请求到响应的完整流程"""
        # 1. 创建请求
        request = RuntimeRequest(
            execution_id="exe_001",
            job_id="job_001",
            model="qwen3-8b",
            messages=[
                Message(role="system", content="You are helpful"),
                Message(role="user", content="Hello"),
            ],
            generation=GenerationParams(
                temperature=0.7,
                max_tokens=500,
            ),
            limits=RuntimeLimits(
                input_tokens=100,
                output_tokens_limit=500,
                max_latency_ms=2000,
            ),
        )
        
        # 2. 转换为字典 (用于传输)
        request_dict = request.to_dict()
        assert request_dict["execution_id"] == "exe_001"
        assert len(request_dict["messages"]) == 2
        
        # 3. 模拟处理
        output = "Hello! How can I help?"
        usage = TokenUsage(input_tokens=100, output_tokens=len(output) // 4)
        
        # 4. 创建响应
        response = RuntimeResponse(
            execution_id=request.execution_id,
            status=RuntimeStatus.COMPLETED,
            output=output,
            usage=usage,
            latency_ms=100,
        )
        
        # 5. 验证响应
        assert response.success is True
        assert response.output == output
        assert response.usage.total_tokens > 0
