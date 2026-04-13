"""
Core Cluster Service
F9: Core Cluster - 集群管理核心服务
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import List, Optional, Dict
from collections import defaultdict

from .models import CoreNode, CoreNodeStatus, ClusterConfig, ClusterMetrics, RoutingStrategy

logger = logging.getLogger(__name__)


class CoreClusterService:
    """
    Core Cluster 核心服务
    
    职责:
    1. 节点注册与心跳
    2. DNS 路由选择
    3. 健康检测与故障转移
    4. P2P 同步协调
    """
    
    def __init__(self, config: ClusterConfig = None):
        self.config = config or ClusterConfig()
        self._nodes: Dict[str, CoreNode] = {}
        self._round_robin_index: Dict[str, int] = defaultdict(int)  # 按节点分组轮询
        self._lock = asyncio.Lock()
        
        logger.info(f"CoreClusterService initialized with {len(self._nodes)} nodes")
    
    # ==================== 节点管理 ====================
    
    async def register_node(self, address: str, port: int = 8000, 
                           weight: int = 1) -> CoreNode:
        """注册新节点"""
        async with self._lock:
            node = CoreNode(
                address=address,
                port=port,
                weight=weight,
                status=CoreNodeStatus.ONLINE,
                last_heartbeat=datetime.utcnow()
            )
            self._nodes[node.node_id] = node
            logger.info(f"Node registered: {node.node_id[:8]}... at {address}:{port}")
            return node
    
    async def heartbeat(self, node_id: str, cpu_usage: float = 0,
                       memory_usage: float = 0, 
                       active_connections: int = 0) -> bool:
        """节点心跳"""
        async with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                logger.warning(f"Heartbeat from unknown node: {node_id[:8]}...")
                return False
            
            node.last_heartbeat = datetime.utcnow()
            node.cpu_usage = cpu_usage
            node.memory_usage = memory_usage
            node.active_connections = active_connections
            node.consecutive_failures = 0
            node.healthy = True
            node.status = CoreNodeStatus.ONLINE
            
            return True
    
    async def get_node(self, node_id: str) -> Optional[CoreNode]:
        """获取节点"""
        return self._nodes.get(node_id)
    
    async def get_all_nodes(self) -> List[CoreNode]:
        """获取所有节点"""
        return list(self._nodes.values())
    
    async def get_healthy_nodes(self) -> List[CoreNode]:
        """获取健康节点"""
        return [n for n in self._nodes.values() if n.healthy]
    
    async def remove_node(self, node_id: str) -> bool:
        """移除节点"""
        async with self._lock:
            if node_id in self._nodes:
                del self._nodes[node_id]
                logger.info(f"Node removed: {node_id[:8]}...")
                return True
            return False
    
    # ==================== DNS 路由 ====================
    
    async def select_node(self) -> Optional[CoreNode]:
        """
        选择节点（基于路由策略）
        """
        healthy_nodes = await self.get_healthy_nodes()
        
        if not healthy_nodes:
            logger.error("No healthy nodes available!")
            return None
        
        if len(healthy_nodes) == 1:
            return healthy_nodes[0]
        
        if self.config.routing_strategy == RoutingStrategy.ROUND_ROBIN:
            return self._round_robin_select(healthy_nodes)
        
        elif self.config.routing_strategy == RoutingStrategy.WEIGHTED:
            return self._weighted_select(healthy_nodes)
        
        elif self.config.routing_strategy == RoutingStrategy.LEAST_CONNECTIONS:
            return self._least_connections_select(healthy_nodes)
        
        # 默认轮询
        return self._round_robin_select(healthy_nodes)
    
    def _round_robin_select(self, nodes: List[CoreNode]) -> CoreNode:
        """轮询选择"""
        # 使用节点列表索引轮询
        if not nodes:
            return None
        
        index = self._round_robin_index['default'] % len(nodes)
        self._round_robin_index['default'] += 1
        return nodes[index]
    
    def _weighted_select(self, nodes: List[CoreNode]) -> CoreNode:
        """加权轮询"""
        total_weight = sum(n.weight for n in nodes)
        if total_weight == 0:
            return random.choice(nodes)
        
        rand = random.random() * total_weight
        cumulative = 0
        
        for node in nodes:
            cumulative += node.weight
            if rand <= cumulative:
                return node
        
        return nodes[-1]
    
    def _least_connections_select(self, nodes: List[CoreNode]) -> CoreNode:
        """最少连接优先"""
        return min(nodes, key=lambda n: n.active_connections)
    
    # ==================== 健康检测 ====================
    
    async def check_node_health(self, node_id: str) -> bool:
        """检查节点健康状态"""
        node = self._nodes.get(node_id)
        if not node:
            return False
        
        # 检查心跳超时
        elapsed = (datetime.utcnow() - node.last_heartbeat).total_seconds()
        if elapsed > self.config.heartbeat_timeout_sec:
            node.healthy = False
            node.status = CoreNodeStatus.OFFLINE
            node.consecutive_failures += 1
            logger.warning(f"Node {node_id[:8]}... heartbeat timeout ({elapsed:.1f}s)")
            
            # 超过最大失败次数，标记为离线
            if node.consecutive_failures >= self.config.max_consecutive_failures:
                node.status = CoreNodeStatus.OFFLINE
                logger.error(f"Node {node_id[:8]}... marked as OFFLINE")
            
            return False
        
        node.healthy = True
        return True
    
    async def check_all_nodes_health(self):
        """检查所有节点健康状态"""
        tasks = [self.check_node_health(node_id) for node_id in self._nodes]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def is_quorum_met(self) -> bool:
        """检查是否满足多数节点要求"""
        healthy = await self.get_healthy_nodes()
        return len(healthy) >= self.config.quorum
    
    # ==================== 集群指标 ====================
    
    def get_metrics(self) -> ClusterMetrics:
        """获取集群指标"""
        nodes = list(self._nodes.values())
        
        metrics = ClusterMetrics(
            total_nodes=len(nodes),
            healthy_nodes=sum(1 for n in nodes if n.healthy),
            online_nodes=sum(1 for n in nodes if n.status == CoreNodeStatus.ONLINE),
            total_requests=sum(n.active_connections for n in nodes),
            avg_latency_ms=sum(n.latency_ms for n in nodes) / max(len(nodes), 1),
        )
        
        return metrics
    
    def get_status(self) -> dict:
        """获取集群状态"""
        metrics = self.get_metrics()
        nodes = [
            {
                "id": n.node_id[:8],
                "address": n.address,
                "status": n.status.value,
                "healthy": n.healthy,
                "latency_ms": n.latency_ms,
                "connections": n.active_connections,
            }
            for n in self._nodes.values()
        ]
        
        return {
            "total_nodes": metrics.total_nodes,
            "healthy_nodes": metrics.healthy_nodes,
            "online_nodes": metrics.online_nodes,
            "quorum_required": self.config.quorum,
            "quorum_met": metrics.online_nodes >= self.config.quorum,
            "nodes": nodes,
            "strategy": self.config.routing_strategy.value,
        }
    
    # ==================== 故障转移 ====================
    
    async def failover(self, failed_node_id: str) -> Optional[CoreNode]:
        """
        故障转移：选择替代节点
        """
        healthy_nodes = await self.get_healthy_nodes()
        
        # 排除失败的节点
        available = [n for n in healthy_nodes if n.node_id != failed_node_id]
        
        if not available:
            logger.error(f"No available nodes for failover (node: {failed_node_id[:8]}...)")
            return None
        
        logger.info(f"Failover from {failed_node_id[:8]}... to {available[0].node_id[:8]}...")
        return available[0]
    
    async def call_with_failover(self, func, *args, **kwargs):
        """
        带故障转移的调用
        """
        healthy_nodes = await self.get_healthy_nodes()
        
        for node in healthy_nodes:
            try:
                result = await func(node, *args, **kwargs)
                return result
            except Exception as e:
                logger.error(f"Call to {node.node_id[:8]}... failed: {e}")
                continue
        
        raise AllNodesFailedError("All nodes failed")


class AllNodesFailedError(Exception):
    """所有节点都失败了"""
    pass


# ==================== 单例 ====================

_cluster_config = ClusterConfig()
core_cluster_service = CoreClusterService(_cluster_config)
