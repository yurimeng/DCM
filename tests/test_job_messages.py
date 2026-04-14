"""
Job Messages 测试 - DCM v3.2
测试 Job 结构中的 messages 字段
"""

import pytest
from src.models.job import Job, JobCreate, Message


class TestMessage:
    """Message 测试"""
    
    def test_create_message(self):
        """创建消息"""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
    
    def test_message_with_metadata(self):
        """带 metadata 的消息"""
        msg = Message(
            role="user",
            content="Hello",
            name="user1",
            metadata={"token_count": 10}
        )
        assert msg.metadata["token_count"] == 10
        assert msg.name == "user1"


class TestJobWithMessages:
    """带 messages 的 Job 测试"""
    
    def test_create_job_with_messages(self):
        """创建带 messages 的 Job"""
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="What is AI?"),
            Message(role="assistant", content="AI is..."),
            Message(role="user", content="Tell me more"),
        ]
        
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,  # <= 256 (config limit)
            max_latency=5000,
            bid_price=0.5,
            messages=messages,
        )
        
        assert len(job.messages) == 4
        assert job.messages[0].role == "system"
        assert job.messages[1].content == "What is AI?"
    
    def test_create_job_with_prompt(self):
        """创建带 prompt 的 Job (兼容)"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            prompt="What is AI?",
        )
        
        assert job.prompt == "What is AI?"
        assert job.messages is None
    
    def test_get_prompt_text_from_messages(self):
        """从 messages 获取 prompt text"""
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="What is AI?"),
        ]
        
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            messages=messages,
        )
        
        # 应该返回最后一个 user message
        prompt = job.get_prompt_text()
        assert prompt == "What is AI?"
    
    def test_get_prompt_text_from_prompt_field(self):
        """从 prompt 字段获取 text"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            prompt="Hello World",
        )
        
        prompt = job.get_prompt_text()
        assert prompt == "Hello World"
    
    def test_get_prompt_text_empty(self):
        """无 messages 和 prompt 时返回空"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
        )
        
        prompt = job.get_prompt_text()
        assert prompt == ""
    
    def test_get_messages_for_runtime(self):
        """获取发送给 Runtime 的 messages"""
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            messages=messages,
        )
        
        runtime_messages = job.get_messages_for_runtime()
        
        assert len(runtime_messages) == 2
        assert runtime_messages[0]["role"] == "system"
        assert isinstance(runtime_messages[0], dict)
    
    def test_get_messages_from_prompt(self):
        """从 prompt 构造 messages"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            prompt="Hello World",
        )
        
        runtime_messages = job.get_messages_for_runtime()
        
        assert len(runtime_messages) == 1
        assert runtime_messages[0]["role"] == "user"
        assert runtime_messages[0]["content"] == "Hello World"
    
    def test_job_with_generation_params(self):
        """带 generation_params 的 Job"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            messages=[Message(role="user", content="Hello")],
            generation_params={
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 200,
            },
        )
        
        assert job.generation_params is not None
        assert job.generation_params["temperature"] == 0.7


class TestJobMessagesCompatibility:
    """Job messages 兼容性测试"""
    
    def test_backward_compatible_with_prompt(self):
        """向后兼容旧的 prompt 字段"""
        # 旧的 API 创建 Job
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            prompt="Hello",
        )
        
        # 新代码应该能处理
        runtime_messages = job.get_messages_for_runtime()
        assert len(runtime_messages) == 1
        assert runtime_messages[0]["content"] == "Hello"
    
    def test_priority_new_messages(self):
        """messages 优先于 prompt"""
        messages = [
            Message(role="user", content="From messages"),
        ]
        
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            messages=messages,
            prompt="From prompt",
        )
        
        # 应该返回 messages 中的内容
        runtime_messages = job.get_messages_for_runtime()
        assert runtime_messages[0]["content"] == "From messages"


class TestJobContextScenarios:
    """Job 上下文场景测试"""
    
    def test_multi_turn_conversation(self):
        """多轮对话场景"""
        messages = [
            Message(role="system", content="You are a helpful assistant"),
            Message(role="user", content="What is fog computing?"),
            Message(role="assistant", content="Fog computing is..."),
            Message(role="user", content="How does it differ from edge computing?"),
        ]
        
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=200,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            messages=messages,
        )
        
        # 验证上下文完整
        assert len(job.messages) == 4
        assert job.messages[1].role == "user"
        assert job.messages[2].role == "assistant"
        
        # Runtime 应该能接收完整上下文
        runtime_messages = job.get_messages_for_runtime()
        assert len(runtime_messages) == 4
    
    def test_single_turn(self):
        """单轮对话"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=50,
            output_tokens_limit=100,
            max_latency=3000,
            bid_price=0.3,
            messages=[
                Message(role="user", content="Hello"),
            ],
        )
        
        assert len(job.messages) == 1
        
        # Runtime 消息
        runtime_messages = job.get_messages_for_runtime()
        assert len(runtime_messages) == 1
