"""
F9: Core Cluster - ClusterService 测试
"""

import pytest
import asyncio
from datetime import datetime, timedelta

import sys
sys.path.insert(0, '.')

from src.core.cluster import (
    CoreClusterService,
    CoreNode,
    CoreNodeStatus,
    ClusterConfig,
    ClusterMetrics,
    RoutingStrategy,
)


@pytest.fixture
def cluster_service():
    """创建 Cluster 服务实例"""
    config = ClusterConfig(
        routing_strategy=RoutingStrategy.ROUND_ROBIN,
        quorum=2,
        heartbeat_timeout_sec=30,
        max_consecutive_failures=3
    )
    return CoreClusterService(config)


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestCoreClusterService:
    """CoreClusterService 测试"""
    
    @pytest.mark.asyncio
    async def test_init(self, cluster_service):
        """测试初始化"""
        assert cluster_service is not None
        assert cluster_service.config is not None
        assert len(cluster_service._nodes) == 0
    
    @pytest.mark.asyncio
    async def test_register_node(self, cluster_service):
        """测试注册节点"""
        node = await cluster_service.register_node(
            address="core1.dcm.io",
            port=8000,
            weight=1
        )
        
        assert node is not None
        assert node.address == "core1.dcm.io"
        assert node.port == 8000
        assert node.weight == 1
        assert node.status == CoreNodeStatus.ONLINE
    
    @pytest.mark.asyncio
    async def test_heartbeat(self, cluster_service):
        """测试心跳"""
        # 先注册节点
        node = await cluster_service.register_node(
            address="core1.dcm.io",
            port=8000
        )
        
        # 发送心跳
        success = await cluster_service.heartbeat(
            node_id=node.node_id,
            cpu_usage=0.5,
            memory_usage=0.3,
            active_connections=10
        )
        
        assert success is True
        
        # 验证节点状态
        updated_node = await cluster_service.get_node(node.node_id)
        assert updated_node.cpu_usage == 0.5
        assert updated_node.memory_usage == 0.3
        assert updated_node.active_connections == 10
    
    @pytest.mark.asyncio
    async def test_get_all_nodes(self, cluster_service):
        """测试获取所有节点"""
        await cluster_service.register_node("core1.dcm.io", 8000)
        await cluster_service.register_node("core2.dcm.io", 8000)
        
        nodes = await cluster_service.get_all_nodes()
        assert len(nodes) == 2
    
    @pytest.mark.asyncio
    async def test_get_healthy_nodes(self, cluster_service):
        """测试获取健康节点"""
        node1 = await cluster_service.register_node("core1.dcm.io", 8000)
        node2 = await cluster_service.register_node("core2.dcm.io", 8000)
        
        # 模拟一个节点不健康
        async with cluster_service._lock:
            cluster_service._nodes[node2.node_id].healthy = False
        
        healthy = await cluster_service.get_healthy_nodes()
        assert len(healthy) == 1
        assert healthy[0].address == "core1.dcm.io"
    
    @pytest.mark.asyncio
    async def test_remove_node(self, cluster_service):
        """测试移除节点"""
        node = await cluster_service.register_node("core1.dcm.io", 8000)
        
        success = await cluster_service.remove_node(node.node_id)
        assert success is True
        
        removed_node = await cluster_service.get_node(node.node_id)
        assert removed_node is None
    
    @pytest.mark.asyncio
    async def test_select_node_round_robin(self, cluster_service):
        """测试轮询选择"""
        await cluster_service.register_node("core1.dcm.io", 8000)
        await cluster_service.register_node("core2.dcm.io", 8000)
        
        # 多次选择，验证轮询
        selected = []
        for _ in range(4):
            node = await cluster_service.select_node()
            if node:
                selected.append(node.address)
        
        # 验证轮询
        assert len(selected) == 4
        assert selected[0] == "core1.dcm.io"
        assert selected[1] == "core2.dcm.io"
        assert selected[2] == "core1.dcm.io"
        assert selected[3] == "core2.dcm.io"
    
    @pytest.mark.asyncio
    async def test_select_node_weighted(self, cluster_service):
        """测试加权选择"""
        cluster_service.config.routing_strategy = RoutingStrategy.WEIGHTED
        
        await cluster_service.register_node("core1.dcm.io", 8000, weight=1)
        await cluster_service.register_node("core2.dcm.io", 8000, weight=3)
        
        # 多次选择，验证加权
        core2_count = 0
        for _ in range(20):
            node = await cluster_service.select_node()
            if node and node.address == "core2.dcm.io":
                core2_count += 1
        
        # core2 权重更高，应该被选中更多
        assert core2_count > 10
    
    @pytest.mark.asyncio
    async def test_select_node_least_connections(self, cluster_service):
        """测试最少连接选择"""
        cluster_service.config.routing_strategy = RoutingStrategy.LEAST_CONNECTIONS
        
        node1 = await cluster_service.register_node("core1.dcm.io", 8000)
        node2 = await cluster_service.register_node("core2.dcm.io", 8000)
        
        # 设置不同连接数
        async with cluster_service._lock:
            cluster_service._nodes[node1.node_id].active_connections = 10
            cluster_service._nodes[node2.node_id].active_connections = 5
        
        # 应该选择连接数少的
        selected = await cluster_service.select_node()
        assert selected.address == "core2.dcm.io"
    
    @pytest.mark.asyncio
    async def test_check_node_health(self, cluster_service):
        """测试健康检查"""
        node = await cluster_service.register_node("core1.dcm.io", 8000)
        
        # 正常心跳
        healthy = await cluster_service.check_node_health(node.node_id)
        assert healthy is True
        
        # 模拟心跳超时
        async with cluster_service._lock:
            cluster_service._nodes[node.node_id].last_heartbeat = datetime.utcnow() - timedelta(seconds=60)
        
        healthy = await cluster_service.check_node_health(node.node_id)
        assert healthy is False
    
    @pytest.mark.asyncio
    async def test_is_quorum_met(self, cluster_service):
        """测试多数节点检查"""
        # quorum = 2
        await cluster_service.register_node("core1.dcm.io", 8000)
        await cluster_service.register_node("core2.dcm.io", 8000)
        
        is_met = await cluster_service.is_quorum_met()
        assert is_met is True
        
        # 移除一个节点
        nodes = await cluster_service.get_all_nodes()
        await cluster_service.remove_node(nodes[0].node_id)
        
        is_met = await cluster_service.is_quorum_met()
        assert is_met is False
    
    @pytest.mark.asyncio
    async def test_get_metrics(self, cluster_service):
        """测试获取指标"""
        await cluster_service.register_node("core1.dcm.io", 8000)
        await cluster_service.register_node("core2.dcm.io", 8000)
        
        metrics = cluster_service.get_metrics()
        
        assert metrics.total_nodes == 2
        assert metrics.healthy_nodes >= 0
        assert metrics.online_nodes >= 0


class TestRoutingStrategy:
    """路由策略测试"""
    
    def test_strategy_values(self):
        """测试策略值"""
        assert RoutingStrategy.ROUND_ROBIN.value == "round_robin"
        assert RoutingStrategy.WEIGHTED.value == "weighted"
        assert RoutingStrategy.LEAST_CONNECTIONS.value == "least_connections"


class TestCoreNodeStatus:
    """节点状态测试"""
    
    def test_status_values(self):
        """测试状态值"""
        assert CoreNodeStatus.ONLINE.value == "online"
        assert CoreNodeStatus.OFFLINE.value == "offline"
        assert CoreNodeStatus.MAINTENANCE.value == "maintenance"
