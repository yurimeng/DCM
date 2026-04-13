"""
F15: Relay Service - Relay 服务

P2P 直连的兜底机制

注意: F13 P2P 已内置 libp2p circuit relay v2 支持
F15 专注于:
1. Relay 节点管理 (Core 兼任)
2. 带宽控制与限速
3. 连接诊断与监控
4. Relay 连接池管理
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable

from .models import (
    RelayConnection,
    RelayNode,
    RelayConfig,
    RelayMetrics,
    RelayConnectionType,
    RelayStatus,
)

logger = logging.getLogger(__name__)


class RelayService:
    """
    Relay 服务
    
    职责:
    1. Relay 节点注册与管理 (Core 节点兼任)
    2. 带宽控制 (per-connection, per-worker, per-relay)
    3. 连接诊断 (判断直连/Relay, 延迟等)
    4. 连接池管理 (Relay 连接追踪)
    
    与 F13 P2P 集成:
    - P2P 直连由 P2PService 处理
    - Relay 连接由 P2PService._try_relay_connect 处理
    - RelayService 负责带宽控制和诊断
    """
    
    def __init__(self, config: Optional[RelayConfig] = None):
        self.config = config or RelayConfig()
        
        # Relay 节点池 (Core 节点)
        self._relay_nodes: Dict[str, RelayNode] = {}
        
        # 活跃 Relay 连接
        self._connections: Dict[str, RelayConnection] = {}
        
        # 回调
        self._on_relay_established: Optional[Callable] = None
        self._on_relay_closed: Optional[Callable] = None
        
        # 指标
        self._metrics = RelayMetrics()
        
        # 延迟统计
        self._relay_latencies: List[int] = []
        
        # 锁
        self._lock = asyncio.Lock()
        
        logger.info("RelayService initialized, enabled=%s", self.config.relay_enabled)
    
    # ==================== 生命周期 ====================
    
    async def start(self):
        """启动 Relay 服务"""
        logger.info("Relay service started")
    
    async def stop(self):
        """停止 Relay 服务"""
        async with self._lock:
            self._connections.clear()
        logger.info("Relay service stopped")
    
    # ==================== Relay 节点管理 ====================
    
    async def register_relay_node(self, peer_id: str, addresses: List[str]) -> RelayNode:
        """注册 Relay 节点 (Core 兼任)"""
        async with self._lock:
            if peer_id in self._relay_nodes:
                node = self._relay_nodes[peer_id]
                node.last_seen = datetime.utcnow()
                return node
            
            node = RelayNode(
                peer_id=peer_id,
                addresses=addresses,
                status=RelayStatus.ENABLED,
                max_bandwidth_bps=self.config.per_relay_total_limit_bps
            )
            self._relay_nodes[peer_id] = node
            
            logger.info(f"Relay node registered: {peer_id[:12]}...")
            return node
    
    async def unregister_relay_node(self, peer_id: str):
        """取消注册 Relay 节点"""
        async with self._lock:
            if peer_id in self._relay_nodes:
                del self._relay_nodes[peer_id]
                logger.info(f"Relay node unregistered: {peer_id[:12]}...")
    
    async def get_relay_node(self, peer_id: str) -> Optional[RelayNode]:
        """获取 Relay 节点"""
        return self._relay_nodes.get(peer_id)
    
    async def get_all_relay_nodes(self) -> List[RelayNode]:
        """获取所有 Relay 节点"""
        return list(self._relay_nodes.values())
    
    async def get_available_relay_node(self) -> Optional[RelayNode]:
        """获取可用的 Relay 节点 (负载最低)"""
        available = [n for n in self._relay_nodes.values() if n.is_available]
        if not available:
            return None
        
        # 选择负载最低的
        return min(available, key=lambda n: n.bandwidth_usage_percent)
    
    # ==================== 连接管理 ====================
    
    async def establish_relay_connection(
        self,
        source_peer_id: str,
        target_peer_id: str,
        relay_node: str,
        connection_type: RelayConnectionType = RelayConnectionType.RELAYED
    ) -> Optional[RelayConnection]:
        """
        建立 Relay 连接
        
        由 F13 P2P Service 调用，当检测到需要通过 Relay 连接时
        """
        if not self.config.relay_enabled:
            logger.warning("Relay is disabled")
            return None
        
        async with self._lock:
            # 检查 Relay 节点容量
            relay_node_obj = self._relay_nodes.get(relay_node)
            if not relay_node_obj:
                logger.warning(f"Relay node not found: {relay_node[:12]}...")
                return None
            
            if relay_node_obj.active_connections >= self.config.max_connections_per_relay:
                logger.warning(f"Relay node overloaded: {relay_node[:12]}...")
                relay_node_obj.status = RelayStatus.OVERLOADED
                return None
            
            # 创建连接
            connection_id = str(uuid.uuid4())
            connection = RelayConnection(
                connection_id=connection_id,
                source_peer_id=source_peer_id,
                target_peer_id=target_peer_id,
                relay_node=relay_node,
                connection_type=connection_type
            )
            
            self._connections[connection_id] = connection
            
            # 更新 Relay 节点统计
            relay_node_obj.active_connections += 1
            relay_node_obj.total_connections += 1
            
            # 更新指标
            self._metrics.total_relay_requests += 1
            self._metrics.active_relay_connections += 1
            
            logger.info(
                f"Relay connection established: {source_peer_id[:12]}... -> "
                f"{target_peer_id[:12]}... via {relay_node[:12]}..."
            )
            
            return connection
    
    async def close_relay_connection(self, connection_id: str):
        """关闭 Relay 连接"""
        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if not connection:
                return
            
            # 更新 Relay 节点统计
            relay_node = self._relay_nodes.get(connection.relay_node)
            if relay_node:
                relay_node.active_connections = max(0, relay_node.active_connections - 1)
                if relay_node.status == RelayStatus.OVERLOADED:
                    relay_node.status = RelayStatus.ENABLED
            
            # 更新指标
            self._metrics.active_relay_connections -= 1
            
            logger.info(f"Relay connection closed: {connection_id}")
    
    async def update_connection_bandwidth(
        self,
        connection_id: str,
        bytes_sent: int = 0,
        bytes_received: int = 0
    ):
        """更新连接带宽统计"""
        async with self._lock:
            connection = self._connections.get(connection_id)
            if not connection:
                return
            
            connection.bytes_sent += bytes_sent
            connection.bytes_received += bytes_received
            connection.update_activity()
            
            # 更新 Relay 节点带宽
            relay_node = self._relay_nodes.get(connection.relay_node)
            if relay_node:
                relay_node.current_bandwidth_bps += (bytes_sent + bytes_received) * 8  # 转换为 bps
            
            # 更新全局带宽
            self._metrics.total_bytes_relayed += bytes_sent + bytes_received
    
    # ==================== 带宽控制 ====================
    
    async def check_bandwidth_limit(self, peer_id: str, required_bps: int) -> bool:
        """
        检查带宽限制
        
        Args:
            peer_id: 请求带宽的节点
            required_bps: 需要的带宽 (bits/s)
        
        Returns:
            True if within limit, False otherwise
        """
        # 检查 per-connection 限制
        if required_bps > self.config.per_connection_limit_bps:
            logger.warning(f"Per-connection limit exceeded: {required_bps} > {self.config.per_connection_limit_bps}")
            return False
        
        return True
    
    async def get_relay_node_capacity(self, relay_node: str) -> dict:
        """获取 Relay 节点容量信息"""
        node = self._relay_nodes.get(relay_node)
        if not node:
            return {"available": False, "reason": "Node not found"}
        
        if node.status == RelayStatus.OVERLOADED:
            return {"available": False, "reason": "Node overloaded"}
        
        return {
            "available": node.is_available,
            "active_connections": node.active_connections,
            "max_connections": self.config.max_connections_per_relay,
            "bandwidth_usage_percent": round(node.bandwidth_usage_percent, 2),
            "remaining_capacity": self.config.max_connections_per_relay - node.active_connections
        }
    
    # ==================== 连接诊断 ====================
    
    async def diagnose_connection(self, peer_id: str) -> Optional[dict]:
        """
        诊断连接类型
        
        Returns:
            - direct: 直连
            - relayed: 通过 Relay
            - unknown: 未知
        """
        # 检查是否有 relay_node 记录
        for conn in self._connections.values():
            if conn.source_peer_id == peer_id or conn.target_peer_id == peer_id:
                return {
                    "peer_id": peer_id,
                    "connection_type": conn.connection_type.value,
                    "relay_node": conn.relay_node if conn.connection_type == RelayConnectionType.RELAYED else None,
                    "connection_id": conn.connection_id,
                    "age_seconds": conn.age_seconds,
                    "bytes_sent": conn.bytes_sent,
                    "bytes_received": conn.bytes_received
                }
        
        return {
            "peer_id": peer_id,
            "connection_type": "unknown",
            "relay_node": None,
            "connection_id": None
        }
    
    # ==================== 指标 ====================
    
    def get_metrics(self) -> dict:
        """获取 Relay 指标"""
        return {
            "total_relay_requests": self._metrics.total_relay_requests,
            "successful_relays": self._metrics.successful_relays,
            "failed_relays": self._metrics.failed_relays,
            "active_relay_connections": self._metrics.active_relay_connections,
            "total_bytes_relayed": self._metrics.total_bytes_relayed,
            "avg_relay_latency_ms": round(self._metrics.avg_relay_latency_ms, 2),
            "direct_fallback_count": self._metrics.direct_fallback_count
        }
    
    def get_status(self) -> dict:
        """获取服务状态"""
        return {
            "relay_enabled": self.config.relay_enabled,
            "relay_nodes_count": len(self._relay_nodes),
            "active_connections": len(self._connections),
            "metrics": self.get_metrics()
        }
    
    # ==================== 配置 ====================
    
    def set_relay_established_callback(self, callback: Callable):
        """设置连接建立回调"""
        self._on_relay_established = callback
    
    def set_relay_closed_callback(self, callback: Callable):
        """设置连接关闭回调"""
        self._on_relay_closed = callback


# ==================== 单例 ====================

relay_service = RelayService()
