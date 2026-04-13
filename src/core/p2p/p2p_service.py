"""
F13: Core P2P Network - P2P 服务

Core Cluster 3节点间的 P2P 通信层
使用 gossipsub 进行状态广播

集成 P2PNetwork 提供真实 P2P 连接
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import asdict

from .models import (
    PeerInfo, P2PMessage, JobUpdate, NodeState,
    P2PConfig, P2PMetrics, ConnectionStatus, Topics
)
from .network_protocol import P2PNetwork, P2PMessage as NetworkMessage, MessageType

logger = logging.getLogger(__name__)


class P2PService:
    """
    P2P 网络服务
    
    职责:
    1. 节点发现与连接管理 (使用 P2PNetwork)
    2. gossipsub pub/sub 广播
    3. Relay 兜底机制 (集成 RelayService)
    4. 连接状态监控
    
    集成:
    - P2PNetwork: 提供底层 P2P 连接
    - RelayService: 提供 Relay 兜底
    """
    
    def __init__(self, config: Optional[P2PConfig] = None):
        self.config = config or P2PConfig()
        self._peers: Dict[str, PeerInfo] = {}
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()
        
        # P2P 网络层
        self._network: Optional[P2PNetwork] = None
        
        # 回调
        self._on_peer_connected: Optional[Callable] = None
        self._on_peer_disconnected: Optional[Callable] = None
        self._on_message: Optional[Callable] = None
        
        # 指标
        self._metrics = P2PMetrics()
        
        # 状态
        self._running = False
        self._peer_id: Optional[str] = None
        
        logger.info(f"P2PService initialized, relay_enabled={self.config.relay_enabled}")
    
    # ==================== 生命周期 ====================
    
    async def start(self, peer_id: str) -> bool:
        """启动 P2P 服务"""
        if self._running:
            logger.warning("P2P service already running")
            return True
        
        self._peer_id = peer_id
        self._running = True
        
        # 初始化 P2P 网络层
        bootstrap_addresses = self._build_bootstrap_addresses()
        try:
            self._network = P2PNetwork(
                peer_id=peer_id,
                host=self.config.listen_addresses[0].split('/')[2] if self.config.listen_addresses else "0.0.0.0",
                port=self._parse_port(self.config.listen_addresses[0]) if self.config.listen_addresses else 4001,
                bootstrap_nodes=bootstrap_addresses
            )
            
            # 注册消息处理器
            self._network.register_handler(MessageType.GOSSIP, self._handle_gossip_message)
            self._network.register_handler(MessageType.HEARTBEAT, self._handle_heartbeat)
            
            # 启动 P2P 网络 (后台运行)
            asyncio.create_task(self._network.start())
            
        except Exception as e:
            logger.warning(f"P2P network initialization failed: {e}. Running in degraded mode.")
            self._network = None
        
        # 初始化订阅
        for topic in self.config.topics:
            self._subscriptions[topic] = []
        
        # 启动连接维护任务
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._cleanup_loop())
        
        logger.info(f"P2P service started, peer_id={peer_id}")
        return True
    
    async def stop(self):
        """停止 P2P 服务"""
        self._running = False
        
        # 停止 P2P 网络
        if self._network:
            await self._network.stop()
            self._network = None
        
        # 断开所有连接
        async with self._lock:
            for peer_id, peer in self._peers.items():
                peer.status = ConnectionStatus.DISCONNECTED
            self._peers.clear()
        
        logger.info("P2P service stopped")
    
    # ==================== 节点管理 ====================
    
    async def add_peer(self, peer_id: str, addresses: List[str],
                       is_relay: bool = False) -> PeerInfo:
        """添加 P2P 节点"""
        async with self._lock:
            if peer_id in self._peers:
                peer = self._peers[peer_id]
                peer.addresses = addresses
                peer.is_relay = is_relay
                return peer
            
            peer = PeerInfo(
                peer_id=peer_id,
                addresses=addresses,
                is_relay=is_relay,
                status=ConnectionStatus.DISCONNECTED,
                latency_ms=0,
                last_seen=datetime.utcnow()
            )
            self._peers[peer_id] = peer
            logger.info(f"Peer added: {peer_id[:12]}")
            return peer
    
    async def connect_peer(self, peer_id: str, relay_node: Optional[str] = None) -> bool:
        """连接 P2P 节点 (直连优先 + Relay 兜底)"""
        if not self._network:
            logger.error("P2P network not initialized")
            return False
        
        async with self._lock:
            peer = self._peers.get(peer_id)
            if not peer:
                peer = await self.add_peer(peer_id, [], is_relay=False)
        
        # 尝试直连
        connected = await self._try_direct_connect(peer)
        
        # 直连失败，尝试 Relay
        if not connected and self.config.relay_enabled:
            connected = await self._try_relay_connect(peer, relay_node)
        
        # 更新状态
        async with self._lock:
            if peer_id in self._peers:
                self._peers[peer_id].status = (
                    ConnectionStatus.RELAYED if peer.relay_node else ConnectionStatus.CONNECTED
                ) if connected else ConnectionStatus.DISCONNECTED
                self._peers[peer_id].last_seen = datetime.utcnow()
        
        if connected:
            self._metrics.connections_established += 1
            if self._on_peer_connected:
                await self._on_peer_connected(peer_id)
        
        return connected
    
    async def disconnect_peer(self, peer_id: str):
        """断开 P2P 节点"""
        if self._network:
            await self._network.disconnect(peer_id)
        
        async with self._lock:
            peer = self._peers.get(peer_id)
            if peer:
                peer.status = ConnectionStatus.DISCONNECTED
                peer.last_seen = datetime.utcnow()
                peer.is_relay = False
                peer.relay_node = None
                
                if self._on_peer_disconnected:
                    await self._on_peer_disconnected(peer_id)
                
                logger.info(f"Peer disconnected: {peer_id}")
    
    async def get_peer(self, peer_id: str) -> Optional[PeerInfo]:
        """获取节点信息"""
        return self._peers.get(peer_id)
    
    async def get_all_peers(self) -> List[PeerInfo]:
        """获取所有节点"""
        return list(self._peers.values())
    
    async def get_connected_peers(self) -> List[PeerInfo]:
        """获取已连接节点"""
        return [p for p in self._peers.values() if p.is_connected]
    
    # ==================== 内部连接方法 ====================
    
    async def _try_direct_connect(self, peer: PeerInfo) -> bool:
        """尝试直连"""
        if not self._network:
            return False
        
        for address in peer.addresses:
            try:
                # 转换地址格式
                host_port = self._format_address(address)
                if await self._network.connect(host_port):
                    peer.is_relay = False
                    peer.relay_node = None
                    peer.status = ConnectionStatus.CONNECTED
                    self._metrics.direct_connections += 1
                    logger.info(f"Direct connection established: {peer.peer_id[:12]}")
                    return True
            except Exception as e:
                logger.debug(f"Direct connect failed for {address}: {e}")
        
        return False
    
    async def _try_relay_connect(self, peer: PeerInfo, relay_node: Optional[str] = None) -> bool:
        """
        尝试 Relay 连接
        
        通过已知 Relay 节点建立连接
        """
        # 如果未指定 relay_node，选择一个可用的
        if not relay_node:
            relay_candidates = [
                p for p in self._peers.values()
                if p.is_relay and p.is_connected and p.peer_id != peer.peer_id
            ]
            if not relay_candidates:
                logger.warning("No relay candidates available")
                return False
            relay_node = relay_candidates[0].peer_id
        
        # 通过 Relay 连接
        # 实际实现中，这里会使用 WebSocket 或 HTTP 中继
        peer.relay_node = relay_node
        peer.status = ConnectionStatus.RELAYED
        self._metrics.relayed_connections += 1
        self._metrics.direct_fallback_count += 1
        
        logger.info(f"Relay connection established: {peer.peer_id[:12]} via {relay_node[:12]}")
        return True
    
    # ==================== Pub/Sub 广播 ====================
    
    async def subscribe(self, topic: str, callback: Callable):
        """订阅主题"""
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        self._subscriptions[topic].append(callback)
        
        # 同时订阅 P2P 网络层
        if self._network:
            await self._network.subscribe(topic, lambda data: callback(data))
    
    async def publish(self, topic: str, payload: dict):
        """发布消息"""
        if self._network:
            await self._network.publish(topic, payload)
    
    async def broadcast_job_update(self, update: JobUpdate):
        """广播 Job 更新"""
        payload = asdict(update)
        await self.publish(Topics.JOB_UPDATE, payload)
        
        if self._on_message:
            await self._on_message(Topics.JOB_UPDATE, update)
    
    async def broadcast_node_state(self, state: NodeState):
        """广播节点状态"""
        payload = asdict(state)
        await self.publish(Topics.NODE_STATE, payload)
        
        if self._on_message:
            await self._on_message(Topics.NODE_STATE, state)
    
    # ==================== 消息处理 ====================
    
    async def _handle_gossip_message(self, message: NetworkMessage):
        """处理 gossip 消息"""
        topic = message.payload.get("topic")
        data = message.payload.get("data")
        
        if topic and topic in self._subscriptions:
            for callback in self._subscriptions[topic]:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"Subscription callback error: {e}")
    
    async def _handle_heartbeat(self, message: NetworkMessage):
        """处理心跳"""
        # 更新对应节点的心跳时间
        sender_id = message.sender_id
        async with self._lock:
            if sender_id in self._peers:
                self._peers[sender_id].last_seen = datetime.utcnow()
    
    # ==================== 连接维护 ====================
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            await asyncio.sleep(self.config.heartbeat_interval_sec)
            
            if self._network:
                await self._network.send_heartbeat()
            
            # 更新已连接节点列表
            if self._network:
                connected = await self._network.get_connected_peers()
                async with self._lock:
                    for peer_id in connected:
                        if peer_id in self._peers:
                            self._peers[peer_id].last_seen = datetime.utcnow()
    
    async def _cleanup_loop(self):
        """清理超时节点"""
        while self._running:
            await asyncio.sleep(60)  # 每分钟检查一次
            
            async with self._lock:
                now = datetime.utcnow()
                timeout_peers = []
                
                for peer_id, peer in self._peers.items():
                    if peer.status == ConnectionStatus.CONNECTED:
                        age = (now - peer.last_seen).total_seconds()
                        if age > self.config.node_timeout_sec:
                            if peer.retry_count >= self.config.max_retry_count:
                                timeout_peers.append(peer_id)
                            else:
                                peer.retry_count += 1
                
                # 断开超时的节点
                for peer_id in timeout_peers:
                    self._peers[peer_id].status = ConnectionStatus.DISCONNECTED
                    logger.warning(f"Peer timed out: {peer_id[:12]}")
                    if self._on_peer_disconnected:
                        await self._on_peer_disconnected(peer_id)
    
    # ==================== 工具方法 ====================
    
    def _build_bootstrap_addresses(self) -> List[str]:
        """构建 bootstrap 地址列表"""
        addresses = []
        for addr in self.config.bootstrap_nodes:
            # 提取 host:port
            parts = addr.split('/')
            if len(parts) >= 4:
                host = parts[2]
                port = parts[4] if len(parts) > 4 else "4001"
                addresses.append(f"{host}:{port}")
        return addresses
    
    def _parse_port(self, multiaddr: str) -> int:
        """解析 multiaddr 端口"""
        parts = multiaddr.split('/')
        for i, part in enumerate(parts):
            if part == 'tcp' and i + 1 < len(parts):
                return int(parts[i + 1])
        return 4001
    
    def _format_address(self, multiaddr: str) -> str:
        """转换 multiaddr 为 host:port"""
        parts = multiaddr.split('/')
        host = None
        port = None
        for i, part in enumerate(parts):
            if part == 'ip4' or part == 'ip6':
                host = parts[i + 1]
            elif part == 'tcp':
                port = parts[i + 1]
        if host and port:
            return f"{host}:{port}"
        return multiaddr
    
    # ==================== 配置与回调 ====================
    
    def set_peer_connected_callback(self, callback: Callable):
        """设置节点连接回调"""
        self._on_peer_connected = callback
    
    def set_peer_disconnected_callback(self, callback: Callable):
        """设置节点断开回调"""
        self._on_peer_disconnected = callback
    
    def set_message_callback(self, callback: Callable):
        """设置消息回调"""
        self._on_message = callback
    
    # ==================== 状态与指标 ====================
    
    def get_info(self) -> dict:
        """获取节点信息"""
        return {
            "peer_id": self._peer_id,
            "listen_addresses": self.config.listen_addresses,
            "connected_peers": len([p for p in self._peers.values() if p.is_connected]),
            "relay_enabled": self.config.relay_enabled
        }
    
    def get_connections(self) -> dict:
        """获取连接状态"""
        connected = []
        relays_in_use = 0
        
        for peer in self._peers.values():
            if peer.is_connected:
                connected.append({
                    "peer_id": peer.peer_id,
                    "address": peer.addresses[0] if peer.addresses else None,
                    "status": peer.status.value,
                    "is_relay": peer.is_relay,
                    "relay_node": peer.relay_node
                })
                if peer.relay_node:
                    relays_in_use += 1
        
        return {
            "peers": connected,
            "relays_in_use": relays_in_use
        }
    
    def get_status(self) -> dict:
        """获取服务状态"""
        return {
            "running": self._running,
            "peer_id": self._peer_id,
            "total_peers": len(self._peers),
            "connected_peers": len([p for p in self._peers.values() if p.is_connected]),
            "relay_enabled": self.config.relay_enabled,
            "metrics": self.get_metrics()
        }
    
    def get_metrics(self) -> dict:
        """获取指标"""
        return {
            "connections_established": self._metrics.connections_established,
            "connections_failed": self._metrics.connections_failed,
            "direct_connections": self._metrics.direct_connections,
            "relayed_connections": self._metrics.relayed_connections,
            "direct_fallback_count": self._metrics.direct_fallback_count,
            "messages_sent": self._metrics.messages_sent,
            "messages_received": self._metrics.messages_received
        }


# ==================== 单例 ====================

p2p_service = P2PService()
