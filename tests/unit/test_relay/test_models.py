"""
F15: Relay Service - 模型测试
"""

import pytest
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '.')

from src.core.relay.models import (
    RelayConnection,
    RelayNode,
    RelayConfig,
    RelayMetrics,
    RelayConnectionType,
    RelayStatus,
)


class TestRelayConnection:
    """RelayConnection 测试"""
    
    def test_create_connection(self):
        """测试创建连接"""
        conn = RelayConnection(
            connection_id="conn-123",
            source_peer_id="QmSource",
            target_peer_id="QmTarget",
            relay_node="QmRelay",
            connection_type=RelayConnectionType.RELAYED
        )
        
        assert conn.connection_id == "conn-123"
        assert conn.source_peer_id == "QmSource"
        assert conn.target_peer_id == "QmTarget"
        assert conn.relay_node == "QmRelay"
        assert conn.connection_type == RelayConnectionType.RELAYED
        assert conn.active is True
    
    def test_age_seconds(self):
        """测试连接年龄计算"""
        conn = RelayConnection(
            connection_id="conn-123",
            source_peer_id="QmSource",
            target_peer_id="QmTarget",
            relay_node="QmRelay",
            connection_type=RelayConnectionType.RELAYED
        )
        
        # 刚创建的连接年龄应该接近 0
        assert conn.age_seconds < 1
    
    def test_update_activity(self):
        """测试更新活动时间"""
        conn = RelayConnection(
            connection_id="conn-123",
            source_peer_id="QmSource",
            target_peer_id="QmTarget",
            relay_node="QmRelay",
            connection_type=RelayConnectionType.RELAYED
        )
        
        old_last_activity = conn.last_activity
        conn.update_activity()
        assert conn.last_activity >= old_last_activity


class TestRelayNode:
    """RelayNode 测试"""
    
    def test_create_node(self):
        """测试创建节点"""
        node = RelayNode(
            peer_id="QmXYZ",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        
        assert node.peer_id == "QmXYZ"
        assert node.status == RelayStatus.ENABLED
        assert node.active_connections == 0
    
    def test_bandwidth_usage_percent(self):
        """测试带宽使用率计算"""
        node = RelayNode(
            peer_id="QmXYZ",
            addresses=["/ip4/1.2.3.4/tcp/4001"],
            max_bandwidth_bps=1000,
            current_bandwidth_bps=500
        )
        
        assert node.bandwidth_usage_percent == 50.0
    
    def test_is_available(self):
        """测试节点可用性"""
        node = RelayNode(
            peer_id="QmXYZ",
            addresses=["/ip4/1.2.3.4/tcp/4001"],
            status=RelayStatus.ENABLED,
            max_bandwidth_bps=1000,
            current_bandwidth_bps=100  # 10% 使用率
        )
        
        assert node.is_available is True
        
        # 高负载时不可用
        node.current_bandwidth_bps = 950  # 95% 使用率
        assert node.is_available is False
        
        # OVERLOADED 状态不可用
        node.status = RelayStatus.OVERLOADED
        assert node.is_available is False


class TestRelayConfig:
    """RelayConfig 测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = RelayConfig()
        
        assert config.relay_enabled is True
        assert config.max_connections_per_relay == 1000
        assert config.per_connection_limit_bps == 10 * 1024 * 1024  # 10 Mbps
        assert config.per_worker_limit_bps == 50 * 1024 * 1024  # 50 Mbps
        assert config.prefer_direct is True
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = RelayConfig(
            relay_enabled=False,
            max_connections_per_relay=500,
            per_connection_limit_bps=5 * 1024 * 1024
        )
        
        assert config.relay_enabled is False
        assert config.max_connections_per_relay == 500
        assert config.per_connection_limit_bps == 5 * 1024 * 1024


class TestRelayMetrics:
    """RelayMetrics 测试"""
    
    def test_default_metrics(self):
        """测试默认指标"""
        metrics = RelayMetrics()
        
        assert metrics.total_relay_requests == 0
        assert metrics.successful_relays == 0
        assert metrics.failed_relays == 0
        assert metrics.active_relay_connections == 0


class TestRelayConnectionType:
    """RelayConnectionType 测试"""
    
    def test_type_values(self):
        """测试类型值"""
        assert RelayConnectionType.DIRECT.value == "direct"
        assert RelayConnectionType.RELAYED.value == "relayed"


class TestRelayStatus:
    """RelayStatus 测试"""
    
    def test_status_values(self):
        """测试状态值"""
        assert RelayStatus.DISABLED.value == "disabled"
        assert RelayStatus.ENABLED.value == "enabled"
        assert RelayStatus.ACTIVE.value == "active"
        assert RelayStatus.OVERLOADED.value == "overloaded"
