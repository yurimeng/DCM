"""
F15: Relay Service - 服务测试
"""

import pytest
import asyncio

import sys
sys.path.insert(0, '.')

from src.core.relay import (
    RelayService,
    RelayConfig,
    RelayConnectionType,
    RelayStatus,
)


@pytest.fixture
def relay_service():
    """创建 Relay 服务实例"""
    config = RelayConfig(
        max_connections_per_relay=100,
        per_connection_limit_bps=10 * 1024 * 1024
    )
    return RelayService(config)


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestRelayService:
    """RelayService 测试"""
    
    @pytest.mark.asyncio
    async def test_start(self, relay_service):
        """测试启动服务"""
        await relay_service.start()
        # 服务启动成功，无异常
    
    @pytest.mark.asyncio
    async def test_stop(self, relay_service):
        """测试停止服务"""
        await relay_service.start()
        await relay_service.stop()
        assert len(relay_service._connections) == 0
    
    @pytest.mark.asyncio
    async def test_register_relay_node(self, relay_service):
        """测试注册 Relay 节点"""
        node = await relay_service.register_relay_node(
            peer_id="QmXYZ",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        
        assert node.peer_id == "QmXYZ"
        assert node.status == RelayStatus.ENABLED
        
        # 再次注册应该更新 last_seen
        node2 = await relay_service.register_relay_node(
            peer_id="QmXYZ",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        assert node2.peer_id == node.peer_id
    
    @pytest.mark.asyncio
    async def test_unregister_relay_node(self, relay_service):
        """测试取消注册 Relay 节点"""
        await relay_service.register_relay_node(
            peer_id="QmXYZ",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        
        await relay_service.unregister_relay_node("QmXYZ")
        
        node = await relay_service.get_relay_node("QmXYZ")
        assert node is None
    
    @pytest.mark.asyncio
    async def test_get_all_relay_nodes(self, relay_service):
        """测试获取所有 Relay 节点"""
        await relay_service.register_relay_node("QmA", ["/ip4/1.2.3.4/tcp/4001"])
        await relay_service.register_relay_node("QmB", ["/ip4/5.6.7.8/tcp/4001"])
        
        nodes = await relay_service.get_all_relay_nodes()
        assert len(nodes) == 2
    
    @pytest.mark.asyncio
    async def test_get_available_relay_node(self, relay_service):
        """测试获取可用 Relay 节点"""
        await relay_service.register_relay_node("QmA", ["/ip4/1.2.3.4/tcp/4001"])
        await relay_service.register_relay_node("QmB", ["/ip4/5.6.7.8/tcp/4001"])
        
        # QmB 负载更低
        node_b = await relay_service.get_relay_node("QmB")
        node_b.current_bandwidth_bps = 10 * 1024 * 1024  # 10 Mbps
        
        node_a = await relay_service.get_relay_node("QmA")
        node_a.current_bandwidth_bps = 100 * 1024 * 1024  # 100 Mbps
        
        available = await relay_service.get_available_relay_node()
        assert available.peer_id == "QmB"
    
    @pytest.mark.asyncio
    async def test_establish_relay_connection(self, relay_service):
        """测试建立 Relay 连接"""
        # 注册 Relay 节点
        await relay_service.register_relay_node(
            "QmRelay",
            ["/ip4/1.2.3.4/tcp/4001"]
        )
        
        # 建立连接
        conn = await relay_service.establish_relay_connection(
            source_peer_id="QmSource",
            target_peer_id="QmTarget",
            relay_node="QmRelay"
        )
        
        assert conn is not None
        assert conn.source_peer_id == "QmSource"
        assert conn.target_peer_id == "QmTarget"
        assert conn.relay_node == "QmRelay"
        
        # 验证 Relay 节点连接数增加
        relay_node = await relay_service.get_relay_node("QmRelay")
        assert relay_node.active_connections == 1
    
    @pytest.mark.asyncio
    async def test_close_relay_connection(self, relay_service):
        """测试关闭 Relay 连接"""
        # 注册 Relay 节点
        await relay_service.register_relay_node(
            "QmRelay",
            ["/ip4/1.2.3.4/tcp/4001"]
        )
        
        # 建立连接
        conn = await relay_service.establish_relay_connection(
            source_peer_id="QmSource",
            target_peer_id="QmTarget",
            relay_node="QmRelay"
        )
        
        conn_id = conn.connection_id
        
        # 关闭连接
        await relay_service.close_relay_connection(conn_id)
        
        # 验证 Relay 节点连接数减少
        relay_node = await relay_service.get_relay_node("QmRelay")
        assert relay_node.active_connections == 0
    
    @pytest.mark.asyncio
    async def test_relay_connection_overload(self, relay_service):
        """测试 Relay 节点过载"""
        # 设置低连接限制
        relay_service.config.max_connections_per_relay = 1
        
        await relay_service.register_relay_node(
            "QmRelay",
            ["/ip4/1.2.3.4/tcp/4001"]
        )
        
        # 建立第一个连接
        conn1 = await relay_service.establish_relay_connection(
            source_peer_id="QmSource1",
            target_peer_id="QmTarget1",
            relay_node="QmRelay"
        )
        assert conn1 is not None
        
        # 尝试建立第二个连接 (应该失败)
        conn2 = await relay_service.establish_relay_connection(
            source_peer_id="QmSource2",
            target_peer_id="QmTarget2",
            relay_node="QmRelay"
        )
        assert conn2 is None
    
    @pytest.mark.asyncio
    async def test_diagnose_connection(self, relay_service):
        """测试连接诊断"""
        # 注册 Relay 节点
        await relay_service.register_relay_node(
            "QmRelay",
            ["/ip4/1.2.3.4/tcp/4001"]
        )
        
        # 建立连接
        await relay_service.establish_relay_connection(
            source_peer_id="QmSource",
            target_peer_id="QmTarget",
            relay_node="QmRelay"
        )
        
        # 诊断
        diagnostics = await relay_service.diagnose_connection("QmSource")
        
        assert diagnostics is not None
        assert diagnostics["connection_type"] == "relayed"
        assert diagnostics["relay_node"] == "QmRelay"
    
    @pytest.mark.asyncio
    async def test_check_bandwidth_limit(self, relay_service):
        """测试带宽限制检查"""
        # 低于限制
        result = await relay_service.check_bandwidth_limit("QmPeer", 5 * 1024 * 1024)
        assert result is True
        
        # 高于限制
        result = await relay_service.check_bandwidth_limit("QmPeer", 20 * 1024 * 1024)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_metrics(self, relay_service):
        """测试指标获取"""
        # 注册 Relay 节点
        await relay_service.register_relay_node(
            "QmRelay",
            ["/ip4/1.2.3.4/tcp/4001"]
        )
        
        # 建立连接
        await relay_service.establish_relay_connection(
            source_peer_id="QmSource",
            target_peer_id="QmTarget",
            relay_node="QmRelay"
        )
        
        metrics = relay_service.get_metrics()
        
        assert metrics["total_relay_requests"] == 1
        assert metrics["active_relay_connections"] == 1
    
    @pytest.mark.asyncio
    async def test_status(self, relay_service):
        """测试状态获取"""
        status = relay_service.get_status()
        
        assert "relay_enabled" in status
        assert "relay_nodes_count" in status
        assert "active_connections" in status
        assert "metrics" in status
