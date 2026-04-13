"""
F14: QUIC Transport - 服务测试
"""

import pytest
import asyncio
import hashlib

import sys
sys.path.insert(0, '.')

from src.core.quic import (
    QUICService,
    QUICConfig,
    InferenceRequest,
    InferenceStatus,
)


@pytest.fixture
def quic_service():
    """创建 QUIC 服务实例"""
    config = QUICConfig(server_port=8443)
    return QUICService(config)


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestQUICService:
    """QUICService 测试"""
    
    @pytest.mark.asyncio
    async def test_start(self, quic_service):
        """测试启动服务"""
        await quic_service.start()
        
        assert quic_service._running is True
    
    @pytest.mark.asyncio
    async def test_stop(self, quic_service):
        """测试停止服务"""
        await quic_service.start()
        await quic_service.stop()
        
        assert quic_service._running is False
    
    @pytest.mark.asyncio
    async def test_create_session(self, quic_service):
        """测试创建会话"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="qwen2.5:7b",
            prompt="Hello",
            max_tokens=256
        )
        
        session = await quic_service.create_session(request)
        
        assert session.job_id == "job-123"
        assert session.status == InferenceStatus.PENDING
        assert quic_service._metrics.total_sessions == 1
        assert quic_service._metrics.active_sessions == 1
    
    @pytest.mark.asyncio
    async def test_get_session(self, quic_service):
        """测试获取会话"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        
        session = await quic_service.get_session("job-123")
        
        assert session is not None
        assert session.job_id == "job-123"
    
    @pytest.mark.asyncio
    async def test_start_inference(self, quic_service):
        """测试开始推理"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        
        success = await quic_service.start_inference("job-123")
        
        assert success is True
        
        session = await quic_service.get_session("job-123")
        assert session.status == InferenceStatus.RUNNING
        assert session.started_at is not None
    
    @pytest.mark.asyncio
    async def test_add_streaming_token(self, quic_service):
        """测试添加 streaming token"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        await quic_service.start_inference("job-123")
        
        await quic_service.add_streaming_token("job-123", "Hello")
        await quic_service.add_streaming_token("job-123", " ")
        await quic_service.add_streaming_token("job-123", "World")
        
        session = await quic_service.get_session("job-123")
        assert session.tokens_count == 3
        assert session.result_text == "Hello World"
        assert session.status == InferenceStatus.STREAMING
    
    @pytest.mark.asyncio
    async def test_complete_inference(self, quic_service):
        """测试完成推理"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        await quic_service.start_inference("job-123")
        await quic_service.add_streaming_token("job-123", "Result")
        
        result = await quic_service.complete_inference("job-123")
        
        assert result is not None
        assert result.job_id == "job-123"
        assert result.tokens_count == 1
        assert result.result_hash != ""
        
        # 验证 hash 计算
        expected_hash = hashlib.sha256("Result".encode()).hexdigest()
        assert result.result_hash == expected_hash
    
    @pytest.mark.asyncio
    async def test_fail_inference(self, quic_service):
        """测试推理失败"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        await quic_service.start_inference("job-123")
        
        result = await quic_service.fail_inference("job-123", "Timeout", "TIMEOUT")
        
        assert result is not None
        assert result.error == "Timeout"
        assert result.error_code == "TIMEOUT"
        
        session = await quic_service.get_session("job-123")
        assert session.status == InferenceStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_get_result(self, quic_service):
        """测试获取结果"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        await quic_service.start_inference("job-123")
        await quic_service.add_streaming_token("job-123", "Done")
        await quic_service.complete_inference("job-123")
        
        result = await quic_service.get_result("job-123")
        
        assert result is not None
        assert result.job_id == "job-123"
    
    @pytest.mark.asyncio
    async def test_get_session_status(self, quic_service):
        """测试获取会话状态"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        
        # 使用 get_session 获取状态
        session = await quic_service.get_session("job-123")
        assert session is not None
        assert session.job_id == "job-123"
        assert session.status == InferenceStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_get_all_sessions(self, quic_service):
        """测试获取所有会话"""
        request1 = InferenceRequest(
            job_id="job-1",
            match_id="match-1",
            model="test",
            prompt="test"
        )
        
        request2 = InferenceRequest(
            job_id="job-2",
            match_id="match-2",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request1)
        await quic_service.create_session(request2)
        
        sessions = await quic_service.get_all_sessions()
        
        assert len(sessions) == 2
    
    @pytest.mark.asyncio
    async def test_get_active_sessions(self, quic_service):
        """测试获取活跃会话"""
        request1 = InferenceRequest(
            job_id="job-1",
            match_id="match-1",
            model="test",
            prompt="test"
        )
        
        request2 = InferenceRequest(
            job_id="job-2",
            match_id="match-2",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request1)
        await quic_service.create_session(request2)
        await quic_service.start_inference("job-1")
        await quic_service.complete_inference("job-1")
        
        active = await quic_service.get_active_sessions()
        
        assert len(active) == 1
        assert active[0].job_id == "job-2"
    
    @pytest.mark.asyncio
    async def test_metrics(self, quic_service):
        """测试指标"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        await quic_service.create_session(request)
        await quic_service.start_inference("job-123")
        await quic_service.add_streaming_token("job-123", "Done")
        await quic_service.complete_inference("job-123")
        
        metrics = quic_service.get_metrics()
        
        assert metrics["total_sessions"] == 1
        assert metrics["completed_sessions"] == 1
        assert metrics["active_sessions"] == 0
        assert metrics["tokens_processed"] == 1
    
    @pytest.mark.asyncio
    async def test_get_status_info(self, quic_service):
        """测试获取服务状态"""
        await quic_service.start()
        
        status = quic_service.get_status()
        
        assert status["running"] is True
        assert status["port"] == 8443
        assert "metrics" in status
