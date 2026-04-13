"""
F13: Core P2P Network - 模型测试
"""

import pytest
from datetime import datetime

import sys
sys.path.insert(0, '.')

from src.core.p2p.models import (
    PeerInfo,
    P2PMessage,
    JobUpdate,
    NodeState,
    P2PConfig,
    P2PMetrics,
    ConnectionStatus,
    Topics,
)


class TestPeerInfo:
    """PeerInfo 测试"""
    
    def test_create_peer_info(self):
        """测试创建 PeerInfo"""
        peer = PeerInfo(
            peer_id="QmABC123",
            addresses=["/ip4/1.2.3.4/tcp/4001"],
            is_relay=False
        )
        
        assert peer.peer_id == "QmABC123"
        assert len(peer.addresses) == 1
        assert peer.is_relay is False
        assert peer.status == ConnectionStatus.DISCONNECTED
    
    def test_is_connected(self):
        """测试 is_connected 属性"""
        peer = PeerInfo(peer_id="QmABC")
        
        peer.status = ConnectionStatus.DISCONNECTED
        assert peer.is_connected is False
        
        peer.status = ConnectionStatus.CONNECTING
        assert peer.is_connected is False
        
        peer.status = ConnectionStatus.CONNECTED
        assert peer.is_connected is True
        
        peer.status = ConnectionStatus.RELAYED
        assert peer.is_connected is True
    
    def test_idle_time_sec(self):
        """测试 idle_time_sec 属性"""
        peer = PeerInfo(peer_id="QmABC")
        peer.last_seen = datetime.utcnow()
        
        # 刚更新，idle time 应该接近 0
        assert peer.idle_time_sec < 1


class TestP2PMessage:
    """P2PMessage 测试"""
    
    def test_create_message(self):
        """测试创建消息"""
        message = P2PMessage(
            topic="test_topic",
            sender_id="QmABC",
            data={"key": "value"}
        )
        
        assert message.topic == "test_topic"
        assert message.sender_id == "QmABC"
        assert message.data["key"] == "value"
    
    def test_job_update(self):
        """测试 JobUpdate"""
        update = JobUpdate(
            sender_id="QmABC",
            data={"job_id": "job-123", "status": "matched"}
        )
        
        assert update.topic == "job_update"
        assert update.data["job_id"] == "job-123"
        assert update.data["status"] == "matched"
    
    def test_node_state(self):
        """测试 NodeState"""
        state = NodeState(
            sender_id="QmABC",
            data={"node_id": "node-456", "state": {"cpu": 50}}
        )
        
        assert state.topic == "node_state"
        assert state.data["node_id"] == "node-456"


class TestP2PConfig:
    """P2PConfig 测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = P2PConfig()
        
        assert config.heartbeat_interval_sec == 30
        assert config.node_timeout_sec == 90
        assert config.max_retry_count == 5
        assert config.relay_enabled is True
        assert "job_update" in config.topics
        assert "node_state" in config.topics
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = P2PConfig(
            heartbeat_interval_sec=60,
            node_timeout_sec=120,
            relay_enabled=False
        )
        
        assert config.heartbeat_interval_sec == 60
        assert config.node_timeout_sec == 120
        assert config.relay_enabled is False


class TestConnectionStatus:
    """ConnectionStatus 测试"""
    
    def test_status_values(self):
        """测试状态值"""
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
        assert ConnectionStatus.CONNECTING.value == "connecting"
        assert ConnectionStatus.CONNECTED.value == "connected"
        assert ConnectionStatus.RELAYED.value == "relayed"


class TestTopics:
    """Topics 测试"""
    
    def test_topic_constants(self):
        """测试 topic 常量"""
        assert Topics.JOB_UPDATE == "job_update"
        assert Topics.NODE_STATE == "node_state"
        assert Topics.MATCH_RESULT == "match_result"
        assert Topics.ESCROW_SYNC == "escrow_sync"
