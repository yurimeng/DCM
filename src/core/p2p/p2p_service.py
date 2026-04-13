"""
F13: Core P2P Network - P2P 服务

Core Cluster 3节点间的 P2P 通信层
使用 gossipsub 进行状态广播
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

logger = logging.getLogger(__name__)


class P2PService:
    """
    P2P 网络服务
    
    职责:
    1. 节点发现与连接管理
    2. gossipsub pub/sub 广播
    3. Relay 兜底机制
    4. 连接状态监控
    """
    
    def __init__(self, config: Optional[P2PConfig] = None):
        self.config = config or P2PConfig()
        self._peers: Dict[str, PeerInfo] = {}
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()
        
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
        
        # 断开所有连接
        async with self._lock:
            self._peers.clear()
        
        logger.info("P2P service stopped")
    
    # ==================== 节点管理 ====================
    
    async def add_peer(self, peer_id: str, addresses: List[str], 
                      is_relay: bool = False) -> PeerInfo:
        """添加 P2P 节点"""
        async with self._lock:
            if peer_id in self._peers:
                return self._peers[peer_id]
            
            peer = PeerInfo(
                peer_id=peer_id,
                addresses=addresses,
                is_relay=is_relay,
                status=ConnectionStatus.CONNECTING
            )
            self._peers[peer_id] = peer
            logger.info(f"Peer added: {peer_id}, addresses={len(addresses)}")
            return peer
    
    async def connect_peer(self, peer_id: str, relay_node: Optional[str] = None) -> bool:
        """连接 P2P 节点"""
        async with self._lock:
            peer = self._peers.get(peer_id)
            if not peer:
                logger.warning(f"Peer not found: {peer_id}")
                return False
            
            # 尝试直连
            connected = await self._try_direct_connect(peer)
            
            if not connected and self.config.relay_enabled:
                # 直连失败，尝试 Relay
                connected = await self._try_relay_connect(peer, relay_node)
            
            if connected:
                peer.status = ConnectionStatus.RELAYED if peer.relay_node else ConnectionStatus.CONNECTED
                peer.last_seen = datetime.utcnow()
                self._metrics.connected_peers = sum(1 for p in self._peers.values() if p.is_connected)
                
                if self._on_peer_connected:
                    await self._on_peer_connected(peer_id)
            else:
                peer.status = ConnectionStatus.DISCONNECTED
                peer.retry_count += 1
                
                if peer.retry_count >= self.config.max_retry_count:
                    logger.error(f"Peer unreachable after {peer.retry_count} retries: {peer_id}")
            
            return connected
    
    async def _try_direct_connect(self, peer: PeerInfo) -> bool:
        """尝试直连"""
        # TODO: 实现 libp2p 直连
        # 这里简化处理，假设直连成功
        peer.is_relay = False
        peer.relay_node = None
        return True
    
    async def _try_relay_connect(self, peer: PeerInfo, relay_node: Optional[str] = None) -> bool:
        """尝试 Relay 连接"""
        # TODO: 实现 libp2p circuit relay v2
        if not relay_node:
            # 选择一个 Core 节点作为 relay
            relay_candidates = [p for p in self._peers.values() if p.is_relay and p.is_connected]
            if not relay_candidates:
                logger.warning("No relay candidates available")
                return False
            relay_node = relay_candidates[0].peer_id
        
        peer.relay_node = relay_node
        peer.status = ConnectionStatus.RELAYED
        return True
    
    async def disconnect_peer(self, peer_id: str):
        """断开 P2P 节点"""
        async with self._lock:
            peer = self._peers.get(peer_id)
            if peer:
                peer.status = ConnectionStatus.DISCONNECTED
                peer.last_seen = datetime.utcnow()
                
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
        """获取已连接的节点"""
        return [p for p in self._peers.values() if p.is_connected]
    
    # ==================== Pub/Sub 广播 ====================
    
    async def subscribe(self, topic: str, callback: Callable):
        """订阅主题"""
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        self._subscriptions[topic].append(callback)
        logger.info(f"Subscribed to topic: {topic}")
    
    async def unsubscribe(self, topic: str, callback: Callable):
        """取消订阅"""
        if topic in self._subscriptions:
            self._subscriptions[topic] = [cb for cb in self._subscriptions[topic] if cb != callback]
    
    async def publish(self, topic: str, message: P2PMessage) -> int:
        """
        发布消息到主题
        返回成功接收的节点数
        """
        if topic not in self._subscriptions:
            logger.warning(f"No subscriptions for topic: {topic}")
            return 0
        
        # 广播到所有订阅者
        recipients = 0
        start_time = datetime.utcnow()
        
        for callback in self._subscriptions[topic]:
            try:
                await callback(message)
                recipients += 1
            except Exception as e:
                logger.error(f"Callback error for topic {topic}: {e}")
        
        # 更新指标
        self._metrics.messages_sent += 1
        self._metrics.last_broadcast = datetime.utcnow()
        latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        self._metrics.broadcast_latency_ms = latency
        
        logger.debug(f"Published to {recipients} subscribers, latency={latency:.2f}ms")
        return recipients
    
    async def broadcast_job_update(self, job_id: str, status: str, match_id: str = "") -> int:
        """广播 Job 更新 (gossipsub job_update)"""
        message = JobUpdate(
            sender_id=self._peer_id or "unknown",
            data={
                "job_id": job_id,
                "status": status,
                "match_id": match_id
            }
        )
        return await self.publish(Topics.JOB_UPDATE, message)
    
    async def broadcast_node_state(self, node_id: str, state: dict) -> int:
        """广播节点状态 (gossipsub node_state)"""
        message = NodeState(
            sender_id=self._peer_id or "unknown",
            data={
                "node_id": node_id,
                "state": state
            }
        )
        return await self.publish(Topics.NODE_STATE, message)
    
    # ==================== 消息处理 ====================
    
    async def handle_message(self, topic: str, sender_id: str, data: dict):
        """处理收到的消息"""
        message = P2PMessage(
            topic=topic,
            sender_id=sender_id,
            data=data
        )
        
        self._metrics.messages_received += 1
        
        if self._on_message:
            await self._on_message(topic, message)
    
    # ==================== 后台任务 ====================
    
    async def _heartbeat_loop(self):
        """心跳循环 - 保持连接活跃"""
        while self._running:
            await asyncio.sleep(self.config.heartbeat_interval_sec)
            
            async with self._lock:
                for peer in self._peers.values():
                    if peer.is_connected:
                        # 发送心跳
                        peer.last_seen = datetime.utcnow()
                        logger.debug(f"Heartbeat sent to {peer.peer_id}")
    
    async def _cleanup_loop(self):
        """清理循环 - 处理超时节点"""
        while self._running:
            await asyncio.sleep(10)
            
            async with self._lock:
                now = datetime.utcnow()
                for peer in list(self._peers.values()):
                    idle_time = (now - peer.last_seen).total_seconds()
                    
                    if idle_time > self.config.node_timeout_sec:
                        logger.warning(f"Peer timeout: {peer.peer_id}, idle={idle_time:.0f}s")
                        
                        # 断开并重连
                        peer.status = ConnectionStatus.DISCONNECTED
                        
                        if peer.retry_count < self.config.max_retry_count:
                            asyncio.create_task(self.connect_peer(peer.peer_id))
                        else:
                            logger.error(f"Peer max retries exceeded: {peer.peer_id}")
    
    # ==================== 状态查询 ====================
    
    def get_info(self) -> dict:
        """获取本地节点信息"""
        return {
            "peer_id": self._peer_id,
            "addresses": self.config.listen_addresses,
            "connected_peers": self._metrics.connected_peers,
            "relay_enabled": self.config.relay_enabled
        }
    
    def get_connections(self) -> dict:
        """获取连接状态"""
        peers = []
        relays_in_use = 0
        
        for peer in self._peers.values():
            peers.append({
                "peer_id": peer.peer_id,
                "address": peer.addresses[0] if peer.addresses else "",
                "status": peer.status.value,
                "is_relay": peer.is_relay,
                "relay_node": peer.relay_node
            })
            
            if peer.status == ConnectionStatus.RELAYED:
                relays_in_use += 1
        
        return {
            "peers": peers,
            "relays_in_use": relays_in_use
        }
    
    def get_metrics(self) -> dict:
        """获取 P2P 指标"""
        return {
            "connected_peers": self._metrics.connected_peers,
            "relayed_connections": self._metrics.relayed_connections,
            "messages_sent": self._metrics.messages_sent,
            "messages_received": self._metrics.messages_received,
            "broadcast_latency_ms": self._metrics.broadcast_latency_ms,
            "last_broadcast": self._metrics.last_broadcast.isoformat() if self._metrics.last_broadcast else None
        }
    
    def get_status(self) -> dict:
        """获取服务状态"""
        return {
            "running": self._running,
            "peer_id": self._peer_id,
            "total_peers": len(self._peers),
            "connected_peers": self._metrics.connected_peers,
            "relay_enabled": self.config.relay_enabled,
            "metrics": self.get_metrics()
        }


# ==================== 单例 ====================

p2p_service = P2PService()
