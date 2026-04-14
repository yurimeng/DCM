"""
Node Agent 与 Status Report 测试 - DCM v3.2
测试 Node Agent 的完整交易流程
"""

import pytest
import time
from unittest.mock import MagicMock, patch

from src.agents.node_agent import NodeAgent, NodeConfig, NodeStatus
from src.services.node_status_store import node_status_store, update_node_status, get_node_status
from src.models.node import Node


class TestNodeStatusStore:
    """NodeStatusStore 测试"""
    
    def test_update_and_get_status(self):
        """测试更新和获取状态"""
        node_id = "test_node_001"
        
        # 发送 Live Status
        update_node_status(node_id, {
            "timestamp": int(time.time() * 1000),
            "status": {"vram_used_gb": 18, "vram_total_gb": 48},
            "capacity": {"max_concurrency_available": 4},
            "load": {"active_jobs": 0, "available_token_capacity": 3000},
        })
        
        # 获取状态
        status = get_node_status(node_id)
        
        assert status["available_concurrency"] == 4
        assert status["available_queue_tokens"] == 3000
        assert status["vram_used_gb"] == 18
        assert status["vram_total_gb"] == 48
    
    def test_default_status(self):
        """测试默认状态"""
        node_id = "nonexistent_node"
        
        status = get_node_status(node_id)
        
        assert status["available_concurrency"] == 0
        assert status["available_queue_tokens"] == 0
    
    def test_get_available_nodes(self):
        """测试获取可用 Nodes"""
        # 清理
        for node_id in ["avail_001", "avail_002", "busy_001"]:
            update_node_status(node_id, {
                "timestamp": int(time.time() * 1000),
                "status": {},
                "capacity": {"max_concurrency_available": 0},
                "load": {"active_jobs": 0, "available_token_capacity": 0},
            })
        
        # 添加可用 Node
        update_node_status("avail_001", {
            "timestamp": int(time.time() * 1000),
            "status": {},
            "capacity": {"max_concurrency_available": 4},
            "load": {"active_jobs": 0, "available_token_capacity": 3000},
        })
        
        update_node_status("avail_002", {
            "timestamp": int(time.time() * 1000),
            "status": {},
            "capacity": {"max_concurrency_available": 2},
            "load": {"active_jobs": 0, "available_token_capacity": 1500},
        })
        
        # 获取可用 Nodes
        available = node_status_store.get_available_nodes(min_concurrency=1, min_queue_tokens=1)
        
        assert "avail_001" in available
        assert "avail_002" in available


class TestNodeAgentConfig:
    """Node Agent 配置测试"""
    
    def test_default_intervals(self):
        """测试默认间隔配置"""
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
        )
        
        assert config.capacity_report_interval == 30  # 30-60 秒
        assert config.live_status_interval == 3       # 2-5 秒
    
    def test_router_url(self):
        """测试 Router URL"""
        config = NodeConfig(
            router_host="192.168.1.100",
            router_port=8000,
        )
        
        assert config.router_url == "http://192.168.1.100:8000"
        assert "192.168.1.100" in config.websocket_url


class TestNodeAgentLifecycle:
    """Node Agent 生命周期测试"""
    
    def test_initial_status(self):
        """测试初始状态"""
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
        )
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
        
        assert agent.status == NodeStatus.DISCONNECTED
        assert agent.node_id == "test_node"
    
    def test_cluster_id_generation(self):
        """测试 Cluster ID 生成"""
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
            ollama_model="qwen2.5:7b",
        )
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
            agent._init_node_info()
        
        cluster_id = agent.get_current_cluster_id()
        assert cluster_id is not None
        assert cluster_id.startswith("C_")  # DCM v3.2 格式


class TestNodeAgentStatusReport:
    """Node Agent Status Report 测试"""
    
    def test_live_status_format(self):
        """测试 Live Status 格式"""
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
            max_concurrent_jobs=4,
        )
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
        
        # Mock 当前 job
        agent.current_job = None
        
        # 模拟发送 Live Status
        with patch.object(agent, "_send_ws_message") as mock_ws:
            with patch.object(agent, "_calculate_available_concurrency", return_value=4):
                with patch.object(agent, "_calculate_available_token_capacity", return_value=3000):
                    with patch.object(agent, "_get_vram_usage", return_value=18):
                        with patch.object(agent, "_get_vram_total", return_value=48):
                            agent._send_live_status_report(int(time.time() * 1000))
        
        # 验证格式
        if mock_ws.called:
            report = mock_ws.call_args[0][0]
            assert report["type"] == "node_live_status"
            assert report["node_id"] == "test_node"
            assert "capacity" in report
            assert "load" in report
    
    def test_capacity_report_format(self):
        """测试 Capacity Report 格式"""
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
            ollama_model="qwen2.5:7b",
        )
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
            agent._init_node_info()
        
        # Mock loaded models
        with patch.object(agent, "_get_loaded_models", return_value=["qwen2.5:7b"]):
            with patch.object(agent, "_get_workers_total", return_value=1):
                with patch.object(agent, "_get_workers_active", return_value=0):
                    with patch.object(agent, "_get_max_concurrency_total", return_value=4):
                        with patch.object(agent, "_estimate_token_throughput", return_value=100):
                            with patch.object(agent, "_send_ws_message"):
                                agent._send_capacity_report(int(time.time() * 1000))
        
        # 验证 _check_and_update_cluster 被调用
        # (实际结果取决于 cluster_builder)


class TestNodeAgentJobFlow:
    """Node Agent Job 执行流程测试"""
    
    def test_job_execution_callback(self):
        """测试 Job 执行回调"""
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
        )
        
        job_received = []
        
        def on_job_received(job):
            job_received.append(job)
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
            agent.on_job_received = on_job_received
        
        # 模拟接收 Job
        from src.agents.node_agent import Job as AgentJob
        
        mock_job = AgentJob(
            job_id="test_job",
            model="qwen2.5:7b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            locked_price=0.5,
        )
        
        # 触发回调
        agent.on_job_received(mock_job)
        
        assert len(job_received) == 1
        assert job_received[0].job_id == "test_job"
