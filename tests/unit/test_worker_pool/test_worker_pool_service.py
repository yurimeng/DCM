"""
F11: Worker Pool - WorkerPoolService 测试
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

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
    
    service._relay_service = MagicMock()
    service._relay_service.diagnose_connection = AsyncMock(return_value={
        "connection_type": "direct",
        "relay_node": None
    })
    
    return service


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestWorkerPoolService:
    """WorkerPoolService 测试"""
    
    @pytest.mark.asyncio
    async def test_init(self, worker_pool_service):
        """测试初始化"""
        assert worker_pool_service is not None
        assert len(worker_pool_service._workers) == 0
    
    @pytest.mark.asyncio
    async def test_register_worker(self, worker_pool_service):
        """测试注册 Worker"""
        worker = await worker_pool_service.register_worker(
            worker_id="worker-1",
            address="192.168.1.100",
            port=8000
        )
        
        assert worker is not None
        assert worker.worker_id == "worker-1"
        assert worker.address == "192.168.1.100"
        assert worker.port == 8000
        assert worker.status == "creating"
    
    @pytest.mark.asyncio
    async def test_heartbeat(self, worker_pool_service):
        """测试心跳"""
        # 先注册
        await worker_pool_service.register_worker(
            worker_id="worker-1",
            address="192.168.1.100"
        )
        
        # 发送心跳
        success = await worker_pool_service.heartbeat(
            worker_id="worker-1",
            status="ready",
            current_requests=5
        )
        
        assert success is True
        
        # 验证状态
        worker = await worker_pool_service.get_worker("worker-1")
        assert worker.status == "ready"
        assert worker.current_requests == 5
    
    @pytest.mark.asyncio
    async def test_get_all_workers(self, worker_pool_service):
        """测试获取所有 Worker"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        await worker_pool_service.register_worker("worker-2", "192.168.1.101")
        
        workers = await worker_pool_service.get_all_workers()
        assert len(workers) == 2
    
    @pytest.mark.asyncio
    async def test_get_ready_workers(self, worker_pool_service):
        """测试获取就绪 Worker"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        await worker_pool_service.register_worker("worker-2", "192.168.1.101")
        
        # 设置为就绪
        await worker_pool_service.heartbeat("worker-1", status="ready")
        await worker_pool_service.heartbeat("worker-2", status="busy")
        
        # 模拟 P2P 连接
        worker_pool_service._workers["worker-1"].p2p_connected = True
        worker_pool_service._workers["worker-2"].p2p_connected = True
        
        ready = await worker_pool_service.get_ready_workers()
        assert len(ready) == 2
    
    @pytest.mark.asyncio
    async def test_remove_worker(self, worker_pool_service):
        """测试移除 Worker"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        
        success = await worker_pool_service.remove_worker("worker-1")
        
        assert success is True
        assert len(worker_pool_service._workers) == 0
    
    @pytest.mark.asyncio
    async def test_select_worker(self, worker_pool_service):
        """测试选择 Worker (最少连接)"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        await worker_pool_service.register_worker("worker-2", "192.168.1.101")
        
        # 设置为就绪，有不同连接数
        worker_pool_service._workers["worker-1"].status = "ready"
        worker_pool_service._workers["worker-1"].current_requests = 10
        worker_pool_service._workers["worker-1"].p2p_connected = True
        
        worker_pool_service._workers["worker-2"].status = "ready"
        worker_pool_service._workers["worker-2"].current_requests = 2
        worker_pool_service._workers["worker-2"].p2p_connected = True
        
        # 选择最少连接的
        selected = await worker_pool_service.select_worker()
        
        assert selected is not None
        assert selected.worker_id == "worker-2"
    
    @pytest.mark.asyncio
    async def test_dispatch_request(self, worker_pool_service):
        """测试分发请求"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        worker_pool_service._workers["worker-1"].status = "ready"
        worker_pool_service._workers["worker-1"].p2p_connected = True
        
        success = await worker_pool_service.dispatch_request("worker-1")
        
        assert success is True
        
        worker = await worker_pool_service.get_worker("worker-1")
        assert worker.current_requests == 1
        assert worker.status == "busy"
    
    @pytest.mark.asyncio
    async def test_complete_request(self, worker_pool_service):
        """测试完成请求"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        worker_pool_service._workers["worker-1"].status = "busy"
        worker_pool_service._workers["worker-1"].current_requests = 1
        
        success = await worker_pool_service.complete_request("worker-1")
        
        assert success is True
        
        worker = await worker_pool_service.get_worker("worker-1")
        assert worker.current_requests == 0
        assert worker.status == "ready"
    
    @pytest.mark.asyncio
    async def test_drain_worker(self, worker_pool_service):
        """测试平滑下线"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        worker_pool_service._workers["worker-1"].status = "busy"
        worker_pool_service._workers["worker-1"].current_requests = 0  # 无待处理请求
        
        # 模拟 drain
        async def mock_drain():
            await worker_pool_service.drain_worker("worker-1")
        
        # 等待 drain 完成
        await mock_drain()
        
        # Worker 应该被移除
        assert "worker-1" not in worker_pool_service._workers
    
    @pytest.mark.asyncio
    async def test_get_status(self, worker_pool_service):
        """测试获取状态"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        await worker_pool_service.register_worker("worker-2", "192.168.1.101")
        
        worker_pool_service._workers["worker-1"].status = "ready"
        # worker-1 的 p2p_connected 由 register_worker 设置为 True (因为 _p2p_service 是 mock)
        
        # worker-2 保持 creating 状态，p2p_connected 也为 True
        
        status = worker_pool_service.get_status()
        
        assert status["total_workers"] == 2
        # 注意: 两个 Worker 的 p2p_connected 都在 register_worker 时设置为 True
        assert status["network_stats"]["p2p_connected"] == 2
    
    @pytest.mark.asyncio
    async def test_get_workers(self, worker_pool_service):
        """测试获取 Worker 列表"""
        await worker_pool_service.register_worker("worker-1", "192.168.1.100")
        
        workers = worker_pool_service.get_workers()
        
        assert len(workers) == 1
        assert workers[0]["worker_id"] == "worker-1"
        assert "p2p_connected" in workers[0]
        assert "relay_node" in workers[0]


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
