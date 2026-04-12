"""
Unit Tests for Node Agent SDK
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock

from src.agents.node_agent import (
    NodeAgent, NodeConfig, Job, JobResult, NodeStatus,
    OllamaClient
)


class TestNodeConfig:
    """测试配置"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = NodeConfig()
        
        assert config.router_host == "localhost"
        assert config.router_port == 8000
        assert config.use_websocket == True
        assert config.poll_interval == 5
    
    def test_router_url(self):
        """测试 Router URL"""
        config = NodeConfig(router_host="192.168.1.1", router_port=9000)
        
        assert config.router_url == "http://192.168.1.1:9000"
    
    def test_websocket_url(self):
        """测试 WebSocket URL"""
        config = NodeConfig(node_id="test-node-001")
        
        assert "ws://" in config.websocket_url
        assert "test-node-001" in config.websocket_url


class TestJob:
    """测试 Job 模型"""
    
    def test_job_from_dict(self):
        """测试从字典创建 Job"""
        data = {
            "job_id": "job-001",
            "model": "llama3-8b",
            "input_tokens": 2048,
            "output_tokens_limit": 1024,
            "max_latency": 5000,
            "locked_price": 0.30,
        }
        
        job = Job.from_dict(data)
        
        assert job.job_id == "job-001"
        assert job.model == "llama3-8b"
        assert job.input_tokens == 2048
        assert job.output_tokens_limit == 1024
        assert job.locked_price == 0.30


class TestOllamaClient:
    """测试 Ollama 客户端"""
    
    def test_is_available_mock(self):
        """测试 Ollama 可用性检查"""
        config = NodeConfig()
        client = OllamaClient(config)
        
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            assert client.is_available() == True
    
    def test_generate_mock(self):
        """测试 Ollama 生成"""
        config = NodeConfig()
        client = OllamaClient(config)
        
        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "response": "Hello world",
                "done": True,
                "total_duration": 3200000000,
                "eval_count": 856,
            }
            mock_post.return_value = mock_response
            
            result = client.generate("Hello", 1024)
            
            assert result["response"] == "Hello world"
            assert result["eval_count"] == 856


class TestNodeAgent:
    """测试 Node Agent"""
    
    def test_agent_creation(self):
        """测试 Agent 创建"""
        config = NodeConfig(node_id="test-node-001")
        agent = NodeAgent(config, "test-node-001")
        
        assert agent.node_id == "test-node-001"
        assert agent.status == NodeStatus.DISCONNECTED
    
    def test_estimate_tokens(self):
        """测试 token 估算"""
        text = "Hello world"  # 11 bytes
        
        tokens = NodeAgent._estimate_tokens(text)
        
        assert tokens == 2  # 11 // 4 = 2
    
    def test_callbacks(self):
        """测试回调设置"""
        config = NodeConfig(node_id="test-node-001")
        agent = NodeAgent(config, "test-node-001")
        
        job_handler = Mock()
        status_handler = Mock()
        error_handler = Mock()
        
        agent.on_job_received = job_handler
        agent.on_status_change = status_handler
        agent.on_error = error_handler
        
        assert agent.on_job_received == job_handler
        assert agent.on_status_change == status_handler
        assert agent.on_error == error_handler


class TestTokenEstimation:
    """测试 Token 估算"""
    
    def test_short_text(self):
        """测试短文本（小于 4 bytes）"""
        text = "Hi"  # 2 bytes UTF-8
        tokens = NodeAgent._estimate_tokens(text)
        assert tokens == 0  # 2 // 4 = 0
    
    def test_long_text(self):
        """测试长文本"""
        text = "A" * 1000
        tokens = NodeAgent._estimate_tokens(text)
        assert tokens == 250  # 1000 // 4
    
    def test_unicode_text(self):
        """测试 Unicode 文本"""
        text = "你好世界"  # UTF-8: 12 bytes
        tokens = NodeAgent._estimate_tokens(text)
        assert tokens == 3  # 12 // 4


class TestJobExecution:
    """测试 Job 执行流程（模拟）"""
    
    @patch("requests.post")
    @patch("requests.get")
    def test_submit_result_success(self, mock_get, mock_post):
        """测试结果提交成功"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        config = NodeConfig(node_id="test-node-001")
        agent = NodeAgent(config, "test-node-001")
        
        job = Job(
            job_id="job-001",
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            locked_price=0.30,
        )
        
        # 模拟提交
        import base64
        result_text = "Hello world"
        result_hash = "abc123"
        
        agent._submit_result(
            job=job,
            result=result_text,
            result_hash=result_hash,
            actual_latency_ms=3000,
            actual_output_tokens=512,
        )
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert job.job_id in call_args[0][0]
    
    def test_job_hash_calculation(self):
        """测试哈希计算"""
        import hashlib
        
        text = "Hello world"
        expected_hash = hashlib.sha256(text.encode()).hexdigest()
        
        # 验证一致性
        computed_hash = hashlib.sha256(text.encode()).hexdigest()
        assert computed_hash == expected_hash
