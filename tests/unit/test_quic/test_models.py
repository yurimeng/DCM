"""
F14: QUIC Transport - 模型测试
"""

import pytest
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '.')

from src.core.quic.models import (
    InferenceRequest,
    InferenceResult,
    InferenceSession,
    StreamingToken,
    InferenceStatus,
    ConnectionState,
    QUICConfig,
    QUICMetrics,
)


class TestInferenceRequest:
    """InferenceRequest 测试"""
    
    def test_create_request(self):
        """测试创建请求"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="qwen2.5:7b",
            prompt="Hello, world!",
            max_tokens=256
        )
        
        assert request.job_id == "job-123"
        assert request.match_id == "match-456"
        assert request.model == "qwen2.5:7b"
        assert request.max_tokens == 256
        assert request.stream is True
        assert request.timeout_ms == 30000
    
    def test_latency_calculation(self):
        """测试延迟计算"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        # 未开始时延迟为 0
        assert request.latency_ms == 0
        
        # 开始推理
        request.start()
        assert request.started_at is not None
        
        # 完成推理
        request.complete()
        assert request.completed_at is not None
        assert request.latency_ms >= 0


class TestStreamingToken:
    """StreamingToken 测试"""
    
    def test_create_token(self):
        """测试创建 token"""
        token = StreamingToken(token="Hello", index=0)
        
        assert token.token == "Hello"
        assert token.index == 0
        assert token.timestamp is not None


class TestInferenceSession:
    """InferenceSession 测试"""
    
    def test_create_session(self):
        """测试创建会话"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        session = InferenceSession(
            job_id=request.job_id,
            match_id=request.match_id,
            request=request
        )
        
        assert session.job_id == "job-123"
        assert session.status == InferenceStatus.PENDING
        assert len(session.tokens) == 0
    
    def test_add_token(self):
        """测试添加 token"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        session = InferenceSession(
            job_id=request.job_id,
            match_id=request.match_id,
            request=request
        )
        
        session.add_token("Hello")
        session.add_token(" ")
        session.add_token("World")
        
        assert session.tokens_count == 3
        assert session.result_text == "Hello World"
    
    def test_is_complete(self):
        """测试完成状态"""
        request = InferenceRequest(
            job_id="job-123",
            match_id="match-456",
            model="test",
            prompt="test"
        )
        
        session = InferenceSession(
            job_id=request.job_id,
            match_id=request.match_id,
            request=request
        )
        
        assert session.is_complete is False
        
        session.status = InferenceStatus.COMPLETED
        assert session.is_complete is True
        
        session.status = InferenceStatus.FAILED
        assert session.is_complete is True


class TestInferenceResult:
    """InferenceResult 测试"""
    
    def test_create_result(self):
        """测试创建结果"""
        result = InferenceResult(
            job_id="job-123",
            result_text="Hello, World!",
            result_hash="abc123",
            tokens_count=3,
            actual_latency_ms=1500
        )
        
        assert result.job_id == "job-123"
        assert result.tokens_count == 3
        assert result.streaming_complete is False
        assert result.error is None


class TestQUICConfig:
    """QUICConfig 测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = QUICConfig()
        
        assert config.server_port == 8443
        assert config.connection_timeout_ms == 10000
        assert config.stream_timeout_ms == 60000
        assert config.enable_0_rtt is True
        assert config.congestion_control == "cubic"
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = QUICConfig(
            server_port=9000,
            max_retry_count=5,
            enable_0_rtt=False
        )
        
        assert config.server_port == 9000
        assert config.max_retry_count == 5
        assert config.enable_0_rtt is False


class TestInferenceStatus:
    """InferenceStatus 测试"""
    
    def test_status_values(self):
        """测试状态值"""
        assert InferenceStatus.PENDING.value == "pending"
        assert InferenceStatus.RUNNING.value == "running"
        assert InferenceStatus.STREAMING.value == "streaming"
        assert InferenceStatus.COMPLETED.value == "completed"
        assert InferenceStatus.FAILED.value == "failed"
        assert InferenceStatus.TIMEOUT.value == "timeout"


class TestConnectionState:
    """ConnectionState 测试"""
    
    def test_state_values(self):
        """测试状态值"""
        assert ConnectionState.IDLE.value == "idle"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.CLOSING.value == "closing"
