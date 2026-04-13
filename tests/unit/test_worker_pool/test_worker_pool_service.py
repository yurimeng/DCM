"""
F11: Worker Pool - WorkerPoolService 测试
网络冗余机制测试
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '.')

from src.core.cluster import (
    WorkerPoolService,
    Worker,
)


@pytest.fixture
def worker_pool_service():
    """创建 WorkerPool 服务实例"""
    service = WorkerPoolService()
    
    # 设置模拟的 P2P 和 Relay 服务
    service._p2p_service = MagicMock()
    service._p2p_service.add_peer = AsyncMock()
    service._p2p_service.disconnect_peer = AsyncMock()
    service._p2p_service.connect_peer = AsyncMock(return_value=True)
    
    service._relay_service = MagicMock()
    service._relay_service.diagnose_connection = AsyncMock(return_value={
        "connection_type": "direct",
        "relay_node": None
    })
    service._relay_service.get_available_relay_node = AsyncMock(return_value=None)
    
    return service


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestWorker:
    """Worker 测试"""
    
    def test_worker_properties(self):
        """测试 Worker 属性"""
        worker = Worker(
            worker_id="worker-1",
            address="192.168.1.100",
            port=8000
        )
        
        assert worker.endpoint == "http://192.168.1.100:8000"
        assert worker.is_available is False  # 状态是 creating，不是 ready/busy
    
    def test_worker_is_available(self):
        """测试 Worker 可用性"""
        worker = Worker(
            worker_id="worker-1",
            address="192.168.1.100",
            status="ready",
            p2p_connected=True
        )
        
        assert worker.is_available is True
        
        # 断网后不可用
        worker.p2p_connected = False
        assert worker.is_available is False
    
    def test_worker_heartbeat_timeout(self):
        """测试心跳超时"""
        worker = Worker(
            worker_id="worker-1",
            address="192.168.1.100",
            status="ready",
            p2p_connected=True,
            last_heartbeat=datetime.utcnow() - timedelta(seconds=120)
        )
        
        # 超时 60 秒
        assert worker.heartbeat_timeout is True
        # 超时后不可用
        assert worker.is_available is False
    
    def test_worker_can_retry(self):
        """测试重试机制"""
        worker = Worker(
            worker_id="worker-1",
            address="192.168.1.100",
            retry_count=3,
            max_retry_count=5
        )
        
        assert worker.can_retry is True
        
        # 达到最大重试次数
        worker.retry_count = 5
        assert worker.can_retry is False
    
    def test_worker_connection_type(self):
        """测试连接类型"""
        worker = Worker(
            worker_id="worker-1",
            address="192.168.1.100",
            connection_type="relayed",
            relay_node="QmRelay123"
        )
        
        assert worker.connection_type == "relayed"
        assert worker.relay_node == "QmRelay123"


class TestWorkerPoolService:
    """WorkerPoolService 测试"""
    
    @pytest.mark.asyncio
    async def test_init(self, worker_pool_service):
        """测试初始化"""
        assert worker_pool_service is not None
        assert len(worker_pool_service._workers) == 0
    
    @pytest.mark.asyncio
    async def test_register_worker_with_redundancy(self, worker_pool_service):
        """测试注册 Worker (带网络冗余)"""
        worker = await worker_pool_service.register_worker(
            worker_id="worker-1",
            address="192.168.1.100",
            port=8000
        )
        
        assert worker is not None
        assert worker.worker_id == "worker-1"
        # P2P 连接由 mock 设置为 True
        assert worker.p2p_connected is True
    
    @pytest.mark.asyncio
    async def test_heartbeat_recovery(self, worker_pool_service):
        """测试心跳恢复网络连接"""
        # 创建不可用的 Worker
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        worker_pool_service._workers["worker-1"].p2p_connected = False
        worker_pool_service._workers["worker-1"].network_failures = 2
        
        # 发送心跳，应该恢复
        success = await worker_pool_service.heartbeat(
            worker_id="worker-1",
            status="ready"
        )
        
        assert success is True
        # 网络应该恢复
        assert worker_pool_service._workers["worker-1"].p2p_connected is True
        # 失败计数应该重置
        assert worker_pool_service._workers["worker-1"].network_failures == 0
    
    @pytest.mark.asyncio
    async def test_get_unavailable_workers(self, worker_pool_service):
        """测试获取不可用 Worker"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        await worker_pool_service.register_worker("worker-2", "192.168.1.101")
        
        worker_pool_service._workers["worker-1"].p2p_connected = True
        worker_pool_service._workers["worker-2"].p2p_connected = False
        
        unavailable = await worker_pool_service.get_unavailable_workers()
        
        assert len(unavailable) == 1
        assert unavailable[0].worker_id == "worker-2"
    
    @pytest.mark.asyncio
    async def test_select_worker_skips_unavailable(self, worker_pool_service):
        """测试选择 Worker 时跳过不可用的"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        await worker_pool_service.register_worker("worker-2", "192.168.1.101")
        
        worker_pool_service._workers["worker-1"].status = "ready"
        worker_pool_service._workers["worker-1"].p2p_connected = True
        worker_pool_service._workers["worker-1"].current_requests = 5
        
        # worker-2 不可用
        worker_pool_service._workers["worker-2"].status = "ready"
        worker_pool_service._workers["worker-2"].p2p_connected = False
        
        selected = await worker_pool_service.select_worker()
        
        # 应该选择 worker-1，跳过不可用的 worker-2
        assert selected is not None
        assert selected.worker_id == "worker-1"
    
    @pytest.mark.asyncio
    async def test_get_status_with_network_stats(self, worker_pool_service):
        """测试获取状态 (含网络统计)"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        await worker_pool_service.register_worker("worker-2", "192.168.1.101")
        
        worker_pool_service._workers["worker-1"].connection_type = "direct"
        worker_pool_service._workers["worker-2"].connection_type = "relayed"
        worker_pool_service._workers["worker-2"].relay_node = "QmRelay"
        
        status = worker_pool_service.get_status()
        
        assert status["total_workers"] == 2
        assert status["network_stats"]["via_direct"] == 1
        assert status["network_stats"]["via_relay"] == 1
    
    @pytest.mark.asyncio
    async def test_dispatch_fails_for_unavailable_worker(self, worker_pool_service):
        """测试分发请求到不可用 Worker 失败"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        worker_pool_service._workers["worker-1"].p2p_connected = False
        worker_pool_service._workers["worker-1"].status = "ready"
        
        success = await worker_pool_service.dispatch_request("worker-1")
        
        assert success is False
    
    @pytest.mark.asyncio
    async def test_worker_network_failure_tracking(self, worker_pool_service):
        """测试 Worker 网络失败追踪"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        
        # 模拟网络失败
        worker_pool_service._workers["worker-1"].p2p_connected = False
        worker_pool_service._workers["worker-1"].network_failures = 1
        
        status = worker_pool_service.get_status()
        
        assert status["network_stats"]["unavailable"] == 1


class TestNetworkRedundancy:
    """网络冗余机制测试"""
    
    @pytest.mark.asyncio
    async def test_direct_to_relay_fallback(self, worker_pool_service):
        """测试直连到 Relay 的回退"""
        # 模拟直连失败
        worker_pool_service._p2p_service.connect_peer = AsyncMock(side_effect=[
            False,  # 直连失败
            True     # Relay 连接成功
        ])
        
        # 模拟获取 Relay 节点
        relay_mock = MagicMock()
        relay_mock.peer_id = "QmRelay123"
        worker_pool_service._relay_service.get_available_relay_node = AsyncMock(
            return_value=relay_mock
        )
        
        worker = await worker_pool_service.register_worker(
            worker_id="worker-1",
            address="192.168.1.100"
        )
        
        # 应该通过 Relay 连接
        assert worker.connection_type == "relayed"
        assert worker.relay_node == "QmRelay123"
    
    @pytest.mark.asyncio
    async def test_retry_mechanism(self, worker_pool_service):
        """测试重试机制"""
        worker = Worker(
            worker_id="worker-1",
            address="192.168.1.100",
            retry_count=0,
            max_retry_count=3
        )
        
        # 模拟重试
        for i in range(3):
            worker.retry_count = i
            assert worker.can_retry is True
        
        # 超过最大重试次数
        worker.retry_count = 3
        assert worker.can_retry is False
