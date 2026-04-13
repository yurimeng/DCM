"""
F13: Core P2P Network - 服务测试
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import sys
sys.path.insert(0, '.')

from src.core.p2p import (
    P2PService,
    P2PConfig,
    PeerInfo,
    ConnectionStatus,
    Topics,
)


@pytest.fixture
def p2p_service():
    """创建 P2P 服务实例"""
    config = P2PConfig(
        listen_addresses=["/ip4/0.0.0.0/tcp/4001"],
        bootstrap_nodes=["/ip4/127.0.0.1/tcp/4002"]
    )
    return P2PService(config)


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestP2PService:
    """P2PService 测试"""
    
    @pytest.mark.asyncio
    async def test_init(self, p2p_service):
        """测试初始化"""
        assert p2p_service is not None
        assert p2p_service.config is not None
        assert p2p_service._running is False
    
    @pytest.mark.asyncio
    async def test_start(self, p2p_service):
        """测试启动服务"""
        success = await p2p_service.start("QmTestPeer123456")
        
        assert success is True
        assert p2p_service._running is True
        assert p2p_service._peer_id == "QmTestPeer123456"
        
        # 清理
        await p2p_service.stop()
    
    @pytest.mark.asyncio
    async def test_stop(self, p2p_service):
        """测试停止服务"""
        await p2p_service.start("QmTestPeer123456")
        await p2p_service.stop()
        
        assert p2p_service._running is False
    
    @pytest.mark.asyncio
    async def test_add_peer(self, p2p_service):
        """测试添加节点"""
        peer = await p2p_service.add_peer(
            peer_id="QmPeer123",
            addresses=["/ip4/1.2.3.4/tcp/4001"],
            is_relay=True
        )
        
        assert peer.peer_id == "QmPeer123"
        assert peer.is_relay is True
        assert peer.status == ConnectionStatus.DISCONNECTED
    
    @pytest.mark.asyncio
    async def test_get_peer(self, p2p_service):
        """测试获取节点"""
        await p2p_service.add_peer(
            peer_id="QmPeer123",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        
        peer = await p2p_service.get_peer("QmPeer123")
        assert peer is not None
        assert peer.peer_id == "QmPeer123"
    
    @pytest.mark.asyncio
    async def test_get_all_peers(self, p2p_service):
        """测试获取所有节点"""
        await p2p_service.add_peer(
            peer_id="QmPeer1",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        await p2p_service.add_peer(
            peer_id="QmPeer2",
            addresses=["/ip4/5.6.7.8/tcp/4001"]
        )
        
        peers = await p2p_service.get_all_peers()
        assert len(peers) == 2
    
    @pytest.mark.asyncio
    async def test_get_connected_peers(self, p2p_service):
        """测试获取已连接节点"""
        await p2p_service.add_peer(
            peer_id="QmPeer1",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        await p2p_service.add_peer(
            peer_id="QmPeer2",
            addresses=["/ip4/5.6.7.8/tcp/4001"]
        )
        
        # 手动设置一个为已连接
        async with p2p_service._lock:
            p2p_service._peers["QmPeer1"].status = ConnectionStatus.CONNECTED
        
        connected = await p2p_service.get_connected_peers()
        assert len(connected) == 1
        assert connected[0].peer_id == "QmPeer1"
    
    @pytest.mark.asyncio
    async def test_disconnect_peer(self, p2p_service):
        """测试断开节点"""
        await p2p_service.add_peer(
            peer_id="QmPeer123",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        
        # 模拟网络层 (使用 AsyncMock)
        p2p_service._network = MagicMock()
        p2p_service._network.disconnect = AsyncMock()
        
        await p2p_service.disconnect_peer("QmPeer123")
        
        peer = await p2p_service.get_peer("QmPeer123")
        assert peer.status == ConnectionStatus.DISCONNECTED
    
    @pytest.mark.asyncio
    async def test_subscribe(self, p2p_service):
        """测试订阅"""
        callback_called = False
        
        async def callback(data):
            nonlocal callback_called
            callback_called = True
        
        await p2p_service.subscribe("test_topic", callback)
        
        assert "test_topic" in p2p_service._subscriptions
        assert len(p2p_service._subscriptions["test_topic"]) == 1
    
    @pytest.mark.asyncio
    async def test_publish(self, p2p_service):
        """测试发布"""
        # 模拟网络层
        p2p_service._network = MagicMock()
        p2p_service._network.publish = AsyncMock()
        
        await p2p_service.publish("test_topic", {"data": "test"})
        
        p2p_service._network.publish.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_broadcast_job_update(self, p2p_service):
        """测试广播 Job 更新"""
        from src.core.p2p import JobUpdate
        
        # 模拟网络层 (使用 AsyncMock)
        p2p_service._network = MagicMock()
        p2p_service._network.publish = AsyncMock()
        
        # 使用正确的构造函数签名
        update = JobUpdate(
            sender_id="QmTestPeer",
            data={
                "job_id": "job-123",
                "status": "completed",
                "match_id": "match-789",
                "result_hash": "abc123"
            }
        )
        
        await p2p_service.broadcast_job_update(update)
        
        p2p_service._network.publish.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_broadcast_node_state(self, p2p_service):
        """测试广播节点状态"""
        from src.core.p2p import NodeState
        
        # 模拟网络层 (使用 AsyncMock)
        p2p_service._network = MagicMock()
        p2p_service._network.publish = AsyncMock()
        
        # 使用正确的构造函数签名
        state = NodeState(
            sender_id="QmTestPeer",
            data={
                "node_id": "node-123",
                "status": "online",
                "gpu_available": True,
                "gpu_type": "A100",
                "vram_gb": 40.0,
                "current_jobs": 2
            }
        )
        
        await p2p_service.broadcast_node_state(state)
        
        p2p_service._network.publish.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_info(self, p2p_service):
        """测试获取节点信息"""
        await p2p_service.start("QmTestPeer")
        
        info = p2p_service.get_info()
        
        assert info["peer_id"] == "QmTestPeer"
        assert "listen_addresses" in info
        assert "relay_enabled" in info
        
        # 清理
        await p2p_service.stop()
    
    @pytest.mark.asyncio
    async def test_get_connections(self, p2p_service):
        """测试获取连接状态"""
        await p2p_service.add_peer(
            peer_id="QmPeer1",
            addresses=["/ip4/1.2.3.4/tcp/4001"]
        )
        
        connections = p2p_service.get_connections()
        
        assert "peers" in connections
        assert "relays_in_use" in connections
    
    @pytest.mark.asyncio
    async def test_get_status(self, p2p_service):
        """测试获取服务状态"""
        # 不启动服务，直接测试
        p2p_service._running = True
        p2p_service._peer_id = "QmTestPeer"
        
        status = p2p_service.get_status()
        
        assert "running" in status
        assert "peer_id" in status
        assert "metrics" in status
        
        # 清理
        p2p_service._running = False
    
    @pytest.mark.asyncio
    async def test_get_metrics(self, p2p_service):
        """测试获取指标"""
        metrics = p2p_service.get_metrics()
        
        assert "connections_established" in metrics
        assert "direct_connections" in metrics
        assert "relayed_connections" in metrics
    
    @pytest.mark.asyncio
    async def test_callbacks(self, p2p_service):
        """测试回调设置"""
        callback = AsyncMock()
        
        p2p_service.set_peer_connected_callback(callback)
        assert p2p_service._on_peer_connected is callback
        
        p2p_service.set_peer_disconnected_callback(callback)
        assert p2p_service._on_peer_disconnected is callback
        
        p2p_service.set_message_callback(callback)
        assert p2p_service._on_message is callback
    
    @pytest.mark.asyncio
    async def test_config(self, p2p_service):
        """测试配置"""
        config = p2p_service.config
        
        assert config.heartbeat_interval_sec == 30
        assert config.node_timeout_sec == 90
        assert config.max_retry_count == 5
        assert config.relay_enabled is True
