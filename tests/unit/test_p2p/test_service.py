"""
F13: Core P2P Network - 服务测试
"""

import pytest
import asyncio

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
        heartbeat_interval_sec=1,  # 测试用短间隔
        node_timeout_sec=5,
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
    async def test_start(self, p2p_service):
        """测试启动服务"""
        success = await p2p_service.start("QmABC123")
        
        assert success is True
        assert p2p_service._running is True
        assert p2p_service._peer_id == "QmABC123"
    
    @pytest.mark.asyncio
    async def test_stop(self, p2p_service):
        """测试停止服务"""
        await p2p_service.start("QmABC123")
        await p2p_service.stop()
        
        assert p2p_service._running is False
    
    @pytest.mark.asyncio
    async def test_add_peer(self, p2p_service):
        """测试添加节点"""
        peer = await p2p_service.add_peer(
            peer_id="QmXYZ",
            addresses=["/ip4/1.2.3.4/tcp/4001"],
            is_relay=True
        )
        
        assert peer.peer_id == "QmXYZ"
        assert peer.is_relay is True
    
    @pytest.mark.asyncio
    async def test_get_peer(self, p2p_service):
        """测试获取节点"""
        await p2p_service.add_peer("QmABC", ["/ip4/1.2.3.4/tcp/4001"])
        
        peer = await p2p_service.get_peer("QmABC")
        
        assert peer is not None
        assert peer.peer_id == "QmABC"
    
    @pytest.mark.asyncio
    async def test_get_all_peers(self, p2p_service):
        """测试获取所有节点"""
        await p2p_service.add_peer("QmA", ["/ip4/1.1.1.1/tcp/4001"])
        await p2p_service.add_peer("QmB", ["/ip4/2.2.2.2/tcp/4001"])
        
        peers = await p2p_service.get_all_peers()
        
        assert len(peers) == 2
    
    @pytest.mark.asyncio
    async def test_connect_peer(self, p2p_service):
        """测试连接节点"""
        await p2p_service.add_peer("QmABC", ["/ip4/1.2.3.4/tcp/4001"])
        
        success = await p2p_service.connect_peer("QmABC")
        
        assert success is True
    
    @pytest.mark.asyncio
    async def test_disconnect_peer(self, p2p_service):
        """测试断开节点"""
        await p2p_service.add_peer("QmABC", ["/ip4/1.2.3.4/tcp/4001"])
        await p2p_service.connect_peer("QmABC")
        
        await p2p_service.disconnect_peer("QmABC")
        
        peer = await p2p_service.get_peer("QmABC")
        assert peer.status == ConnectionStatus.DISCONNECTED
    
    @pytest.mark.asyncio
    async def test_subscribe(self, p2p_service):
        """测试订阅主题"""
        called = False
        
        async def callback(msg):
            nonlocal called
            called = True
        
        await p2p_service.subscribe("test_topic", callback)
        
        assert "test_topic" in p2p_service._subscriptions
        assert callback in p2p_service._subscriptions["test_topic"]
    
    @pytest.mark.asyncio
    async def test_publish(self, p2p_service):
        """测试发布消息"""
        received = []
        
        async def callback(msg):
            received.append(msg)
        
        await p2p_service.subscribe("test_topic", callback)
        
        from src.core.p2p.models import P2PMessage
        message = P2PMessage(
            topic="test_topic",
            sender_id="QmABC",
            data={"key": "value"}
        )
        
        recipients = await p2p_service.publish("test_topic", message)
        
        assert recipients == 1
        assert len(received) == 1
    
    @pytest.mark.asyncio
    async def test_broadcast_job_update(self, p2p_service):
        """测试广播 Job 更新"""
        received = []
        
        async def callback(msg):
            received.append(msg)
        
        await p2p_service.subscribe(Topics.JOB_UPDATE, callback)
        
        recipients = await p2p_service.broadcast_job_update(
            job_id="job-123",
            status="matched",
            match_id="match-456"
        )
        
        assert recipients == 1
        assert len(received) == 1
        assert received[0].data["job_id"] == "job-123"
    
    @pytest.mark.asyncio
    async def test_get_info(self, p2p_service):
        """测试获取节点信息"""
        await p2p_service.start("QmABC123")
        
        info = p2p_service.get_info()
        
        assert info["peer_id"] == "QmABC123"
        assert info["relay_enabled"] is True
    
    @pytest.mark.asyncio
    async def test_get_connections(self, p2p_service):
        """测试获取连接状态"""
        connections = p2p_service.get_connections()
        
        assert "peers" in connections
        assert "relays_in_use" in connections
    
    @pytest.mark.asyncio
    async def test_get_status(self, p2p_service):
        """测试获取服务状态"""
        await p2p_service.start("QmABC")
        
        status = p2p_service.get_status()
        
        assert status["running"] is True
        assert status["peer_id"] == "QmABC"
        assert "metrics" in status
