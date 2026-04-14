"""
E2E Runtime 测试 - DCM v3.2
测试完整的 Job → Runtime 执行流程
"""

import pytest
import time
from src.models.job import Job, Message
from src.models.runtime_protocol import (
    RuntimeRequest, RuntimeResponse, RuntimeStatus,
    OllamaAdapter, VLLMAdapter, create_runtime_adapter,
    Message as ProtoMessage
)


class TestLocalOllamaRuntime:
    """本地 Ollama Runtime 测试"""
    
    @pytest.fixture
    def adapter(self):
        """创建 Ollama 适配器"""
        return OllamaAdapter(host="localhost", port=11434, timeout=60)
    
    def test_ollama_available(self, adapter):
        """测试 Ollama 是否可用"""
        assert adapter.is_available() is True
    
    def test_list_models(self, adapter):
        """测试列出模型"""
        models = adapter.list_models()
        assert len(models) > 0
        print(f"可用模型: {models}")
    
    def test_simple_generation(self, adapter):
        """简单生成测试"""
        request = RuntimeRequest(
            execution_id="test_001",
            job_id="job_test",
            model="qwen2.5:7b",
            messages=[
                ProtoMessage(role="user", content="What is 2+2?")
            ],
        )
        
        response = adapter.generate(request)
        
        print(f"Status: {response.status}")
        print(f"Output: {response.output[:100]}...")
        print(f"Latency: {response.latency_ms}ms")
        
        assert response.success is True
        assert len(response.output) > 0
        assert response.latency_ms > 0
    
    def test_multi_turn_conversation(self, adapter):
        """多轮对话测试"""
        request = RuntimeRequest(
            execution_id="test_002",
            job_id="job_test",
            model="qwen2.5:7b",
            messages=[
                ProtoMessage(role="system", content="You are a helpful assistant"),
                ProtoMessage(role="user", content="What is fog computing?"),
                ProtoMessage(role="assistant", content="Fog computing is..."),
                ProtoMessage(role="user", content="How does it compare to edge computing?"),
            ],
        )
        
        response = adapter.generate(request)
        
        print(f"Status: {response.status}")
        print(f"Output: {response.output[:200]}...")
        
        assert response.success is True
        assert len(response.output) > 0
    
    def test_generation_params(self, adapter):
        """测试生成参数"""
        from src.models.runtime_protocol import GenerationParams
        
        request = RuntimeRequest(
            execution_id="test_003",
            job_id="job_test",
            model="qwen2.5:7b",
            messages=[
                ProtoMessage(role="user", content="Count to 5")
            ],
            generation=GenerationParams(
                temperature=0.1,  # 低温度，结果更确定
                max_tokens=50,
            ),
        )
        
        response = adapter.generate(request)
        
        print(f"Output: {response.output}")
        
        assert response.success is True
        assert len(response.output) > 0


class TestJobToRuntime:
    """Job 到 Runtime 完整流程测试"""
    
    def test_job_messages_to_runtime_request(self):
        """测试 Job.messages 转换为 RuntimeRequest"""
        job = Job(
            model_requirement="qwen2.5:7b",
            input_tokens=100,
            output_tokens_limit=200,
            max_latency=5000,
            bid_price=0.5,
            messages=[
                Message(role="system", content="You are a helpful assistant"),
                Message(role="user", content="Hello"),
            ],
            generation_params={
                "temperature": 0.7,
                "max_tokens": 200,
            },
        )
        
        # 转换为 RuntimeRequest
        request = RuntimeRequest.from_job(
            job_id=job.job_id,
            execution_id=f"exe_{job.job_id}",
            model=job.model_requirement or "qwen2.5:7b",
            messages=[
                ProtoMessage(role=m.role, content=m.content)
                for m in (job.messages or [])
            ],
            generation_params=job.generation_params,
            job_limits={
                "input_tokens": job.input_tokens,
                "output_tokens_limit": job.output_tokens_limit,
                "max_latency_ms": job.max_latency,
            },
        )
        
        assert request.job_id == job.job_id
        assert len(request.messages) == 2
        assert request.generation.max_tokens == 200


class TestEndToEndFlow:
    """端到端流程测试（需要本地 Ollama）"""
    
    def test_full_job_execution(self):
        """完整 Job 执行流程"""
        # 1. 创建 Job
        job = Job(
            model_requirement="qwen2.5:7b",
            input_tokens=50,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
            messages=[
                Message(role="system", content="You are a helpful coding assistant"),
                Message(role="user", content="What is the capital of France?"),
            ],
        )
        
        print(f"Job created: {job.job_id}")
        print(f"Model: {job.model_requirement}")
        print(f"Messages: {len(job.messages)}")
        
        # 2. 创建 Runtime Request
        request = RuntimeRequest(
            execution_id=f"exe_{job.job_id}",
            job_id=job.job_id,
            model=job.model_requirement or "qwen2.5:7b",
            messages=[
                ProtoMessage(role=m.role, content=m.content)
                for m in job.messages
            ],
        )
        
        # 3. 调用 Runtime
        adapter = OllamaAdapter(host="localhost", port=11434, timeout=60)
        
        start = time.time()
        response = adapter.generate(request)
        latency = (time.time() - start) * 1000
        
        print(f"\nRuntime Response:")
        print(f"  Status: {response.status}")
        print(f"  Output: {response.output}")
        print(f"  Latency: {latency:.0f}ms")
        print(f"  Usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}")
        
        # 4. 验证结果
        assert response.success is True
        assert "Paris" in response.output or "paris" in response.output.lower()
        
        print("\n✓ 端到端测试通过!")
    
    @pytest.mark.skipif(
        True,  # 跳过，因为需要较长时间
        reason="Long running test"
    )
    def test_concurrent_jobs(self):
        """并发 Job 测试"""
        import concurrent.futures
        
        adapter = OllamaAdapter(host="localhost", port=11434, timeout=60)
        
        def execute_job(i):
            request = RuntimeRequest(
                execution_id=f"exe_{i}",
                job_id=f"job_{i}",
                model="qwen2.5:7b",
                messages=[
                    ProtoMessage(role="user", content=f"Hello, this is request {i}")
                ],
            )
            return adapter.generate(request)
        
        # 并发执行 3 个 job
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(execute_job, i) for i in range(3)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        success_count = sum(1 for r in results if r.success)
        print(f"成功: {success_count}/3")
        
        assert success_count >= 2  # 至少 2 个成功（考虑并发限制）
