"""
F13: P2P 网络协议实现

基于 asyncio 的轻量级 P2P 实现
- 节点发现: 种子节点列表 + 心跳
- 连接管理: TCP 连接池
- 状态广播: 简化版 gossipsub
- Relay: WebSocket 中继

后续可替换为真正的 libp2p 实现
"""

import asyncio
import json
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Set
from asyncio import StreamReader, StreamWriter

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """P2P 消息类型"""
    HANDSHAKE = "handshake"           # 握手
    HEARTBEAT = "heartbeat"           # 心跳
    DISCOVERY = "discovery"           # 节点发现
    GOSSIP = "gossip"                 # 广播消息
    RELAY_REQUEST = "relay_request"   # Relay 请求
    RELAY_RESPONSE = "relay_response" # Relay 响应
    PEER_LIST = "peer_list"           # 节点列表


@dataclass
class P2PMessage:
    """P2P 消息"""
    msg_type: MessageType
    sender_id: str
    payload: dict
    timestamp: datetime = field(default_factory=datetime.utcnow)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    def to_bytes(self) -> bytes:
        data = {
            "type": self.msg_type.value,
            "sender_id": self.sender_id,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id
        }
        return json.dumps(data).encode('utf-8')
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'P2PMessage':
        parsed = json.loads(data.decode('utf-8'))
        return cls(
            msg_type=MessageType(parsed["type"]),
            sender_id=parsed["sender_id"],
            payload=parsed["payload"],
            timestamp=datetime.fromisoformat(parsed["timestamp"]),
            message_id=parsed["message_id"]
        )


@dataclass
class PeerConnection:
    """P2P 连接"""
    peer_id: str
    reader: StreamReader
    writer: StreamWriter
    address: str
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    topics: Set[str] = field(default_factory=set)
    
    async def send(self, message: P2PMessage):
        """发送消息"""
        try:
            data = message.to_bytes()
            length = len(data)
            # 发送长度前缀 + 消息
            self.writer.write(length.to_bytes(4, 'big'))
            self.writer.write(data)
            await self.writer.drain()
        except Exception as e:
            logger.error(f"Failed to send to {self.peer_id}: {e}")
            raise
    
    async def receive(self) -> Optional[P2PMessage]:
        """接收消息"""
        try:
            # 读取长度前缀
            length_data = await self.reader.read(4)
            if not length_data:
                return None
            
            length = int.from_bytes(length_data, 'big')
            
            # 读取消息体
            data = await self.reader.readexactly(length)
            return P2PMessage.from_bytes(data)
        except Exception as e:
            logger.error(f"Failed to receive from {self.peer_id}: {e}")
            return None
    
    def close(self):
        """关闭连接"""
        try:
            self.writer.close()
        except Exception:
            pass


class P2PNetwork:
    """
    P2P 网络层
    
    提供:
    - 节点发现与连接
    - 消息广播 (gossipsub)
    - 心跳与超时检测
    """
    
    def __init__(
        self,
        peer_id: str,
        host: str = "0.0.0.0",
        port: int = 4001,
        bootstrap_nodes: Optional[List[str]] = None
    ):
        self.peer_id = peer_id
        self.host = host
        self.port = port
        
        # 连接管理
        self._connections: Dict[str, PeerConnection] = {}
        self._lock = asyncio.Lock()
        
        # 种子节点
        self._bootstrap_nodes = bootstrap_nodes or []
        
        # 回调
        self._message_handlers: Dict[MessageType, List[Callable]] = {}
        self._gossip_subscriptions: Dict[str, List[Callable]] = {}
        
        # 已接收消息 (用于去重)
        self._seen_messages: Set[str] = set()
        
        # 服务器
        self._server: Optional[asyncio.Server] = None
        self._running = False
        
        logger.info(f"P2PNetwork initialized: peer_id={peer_id[:12]}, port={port}")
    
    # ==================== 生命周期 ====================
    
    async def start(self):
        """启动 P2P 网络"""
        self._running = True
        
        # 启动服务器
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port
        )
        
        logger.info(f"P2P server started on {self.host}:{self.port}")
        
        # 连接种子节点
        await self._connect_to_bootstrap()
    
    async def stop(self):
        """停止 P2P 网络"""
        self._running = False
        
        # 关闭所有连接
        async with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
        
        # 关闭服务器
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        logger.info("P2P network stopped")
    
    # ==================== 连接管理 ====================
    
    async def connect(self, address: str) -> bool:
        """
        连接到远程节点
        
        Args:
            address: 地址格式 "host:port"
        
        Returns:
            True if connected successfully
        """
        try:
            host, port = address.split(':')
            port = int(port)
            
            reader, writer = await asyncio.open_connection(host, port)
            
            # 发送握手
            handshake = P2PMessage(
                msg_type=MessageType.HANDSHAKE,
                sender_id=self.peer_id,
                payload={
                    "address": f"{self.host}:{self.port}",
                    "version": "1.0"
                }
            )
            await self._send_to_writer(writer, handshake)
            
            # 等待握手响应
            response = await self._receive_from_reader(reader)
            if not response or response.msg_type != MessageType.HANDSHAKE:
                writer.close()
                return False
            
            remote_peer_id = response.sender_id
            
            # 创建连接对象
            conn = PeerConnection(
                peer_id=remote_peer_id,
                reader=reader,
                writer=writer,
                address=address
            )
            
            async with self._lock:
                self._connections[remote_peer_id] = conn
            
            logger.info(f"Connected to {remote_peer_id[:12]} at {address}")
            
            # 启动消息接收循环
            asyncio.create_task(self._receive_loop(conn))
            
            # 请求节点列表
            await self._request_peer_list(conn)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to {address}: {e}")
            return False
    
    async def disconnect(self, peer_id: str):
        """断开连接"""
        async with self._lock:
            conn = self._connections.pop(peer_id, None)
            if conn:
                conn.close()
                logger.info(f"Disconnected from {peer_id[:12]}")
    
    async def get_connected_peers(self) -> List[str]:
        """获取已连接节点 ID 列表"""
        async with self._lock:
            return list(self._connections.keys())
    
    # ==================== 消息处理 ====================
    
    async def subscribe(self, topic: str, handler: Callable[[P2PMessage], None]):
        """订阅主题"""
        if topic not in self._gossip_subscriptions:
            self._gossip_subscriptions[topic] = []
        self._gossip_subscriptions[topic].append(handler)
        logger.info(f"Subscribed to topic: {topic}")
    
    async def publish(self, topic: str, payload: dict):
        """
        发布消息到主题 (gossipsub)
        
        消息会被广播到所有订阅该主题的节点
        """
        message = P2PMessage(
            msg_type=MessageType.GOSSIP,
            sender_id=self.peer_id,
            payload={
                "topic": topic,
                "data": payload
            }
        )
        
        # 去重
        if message.message_id in self._seen_messages:
            return
        self._seen_messages.add(message.message_id)
        
        # 广播到所有连接
        async with self._lock:
            for conn in self._connections.values():
                try:
                    await conn.send(message)
                except Exception as e:
                    logger.error(f"Failed to publish to {conn.peer_id[:12]}: {e}")
        
        # 本地处理
        await self._handle_gossip(topic, payload)
    
    def register_handler(self, msg_type: MessageType, handler: Callable):
        """注册消息处理器"""
        if msg_type not in self._message_handlers:
            self._message_handlers[msg_type] = []
        self._message_handlers[msg_type].append(handler)
    
    # ==================== 内部方法 ====================
    
    async def _handle_connection(self, reader: StreamReader, writer: StreamWriter):
        """处理入站连接"""
        try:
            # 等待握手
            handshake = await self._receive_from_reader(reader)
            if not handshake or handshake.msg_type != MessageType.HANDSHAKE:
                writer.close()
                return
            
            remote_peer_id = handshake.sender_id
            remote_address = handshake.payload.get("address", "unknown")
            
            # 发送握手响应
            response = P2PMessage(
                msg_type=MessageType.HANDSHAKE,
                sender_id=self.peer_id,
                payload={"address": f"{self.host}:{self.port}"}
            )
            await self._send_to_writer(writer, response)
            
            # 创建连接对象
            conn = PeerConnection(
                peer_id=remote_peer_id,
                reader=reader,
                writer=writer,
                address=remote_address
            )
            
            async with self._lock:
                self._connections[remote_peer_id] = conn
            
            logger.info(f"New connection from {remote_peer_id[:12]}")
            
            # 启动消息接收循环
            await self._receive_loop(conn)
            
        except Exception as e:
            logger.error(f"Connection handler error: {e}")
            writer.close()
        finally:
            # 连接断开时清理
            async with self._lock:
                for peer_id, c in list(self._connections.items()):
                    if c.writer == writer:
                        del self._connections[peer_id]
                        logger.info(f"Connection closed: {peer_id[:12]}")
                        break
    
    async def _receive_loop(self, conn: PeerConnection):
        """消息接收循环"""
        try:
            while self._running:
                message = await conn.receive()
                if not message:
                    break
                await self._handle_message(conn, message)
        except Exception as e:
            logger.error(f"Receive loop error for {conn.peer_id[:12]}: {e}")
        finally:
            await self.disconnect(conn.peer_id)
    
    async def _handle_message(self, conn: PeerConnection, message: P2PMessage):
        """处理接收到的消息"""
        # 去重
        if message.message_id in self._seen_messages:
            return
        self._seen_messages.add(message.message_id)
        
        # 更新心跳
        conn.last_heartbeat = datetime.utcnow()
        
        # 路由消息
        if message.msg_type == MessageType.GOSSIP:
            topic = message.payload.get("topic")
            data = message.payload.get("data")
            
            # 继续广播 (概率性)
            await self._propagate_gossip(message, conn.peer_id)
            
            # 本地处理
            if topic:
                await self._handle_gossip(topic, data)
        
        elif message.msg_type == MessageType.HEARTBEAT:
            # 心跳响应
            pass
        
        elif message.msg_type == MessageType.PEER_LIST:
            # 处理节点列表
            await self._handle_peer_list(message.payload)
        
        # 调用注册的处理器
        if message.msg_type in self._message_handlers:
            for handler in self._message_handlers[message.msg_type]:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"Handler error: {e}")
    
    async def _handle_gossip(self, topic: str, data: dict):
        """处理 gossip 消息"""
        if topic in self._gossip_subscriptions:
            for handler in self._gossip_subscriptions[topic]:
                try:
                    await handler(data)
                except Exception as e:
                    logger.error(f"Gossip handler error: {e}")
    
    async def _propagate_gossip(self, message: P2PMessage, from_peer: str):
        """
        传播 gossip 消息
        
        简化版 gossipsub: 随机转发给部分邻居
        """
        async with self._lock:
            neighbors = [
                (pid, conn) for pid, conn in self._connections.items()
                if pid != from_peer
            ]
        
        if not neighbors:
            return
        
        # 随机选择部分邻居转发 (覆盖率 ~30%)
        import random
        to_forward = random.sample(neighbors, max(1, len(neighbors) // 3))
        
        for pid, conn in to_forward:
            try:
                await conn.send(message)
            except Exception as e:
                logger.error(f"Failed to propagate to {pid[:12]}: {e}")
    
    async def _handle_peer_list(self, payload: dict):
        """处理节点列表"""
        peers = payload.get("peers", [])
        for peer_address in peers:
            if peer_address != f"{self.host}:{self.port}":
                asyncio.create_task(self.connect(peer_address))
    
    async def _request_peer_list(self, conn: PeerConnection):
        """请求节点列表"""
        message = P2PMessage(
            msg_type=MessageType.PEER_LIST,
            sender_id=self.peer_id,
            payload={"request": True}
        )
        await conn.send(message)
    
    async def _connect_to_bootstrap(self):
        """连接到种子节点"""
        for address in self._bootstrap_nodes:
            try:
                await self.connect(address)
                logger.info(f"Connected to bootstrap node: {address}")
                break  # 成功一个就够了
            except Exception as e:
                logger.warning(f"Failed to connect to bootstrap {address}: {e}")
    
    async def _send_to_writer(self, writer: StreamWriter, message: P2PMessage):
        """发送消息到 writer"""
        data = message.to_bytes()
        length = len(data)
        writer.write(length.to_bytes(4, 'big'))
        await writer.drain()
        writer.write(data)
        await writer.drain()
    
    async def _receive_from_reader(self, reader: StreamReader) -> Optional[P2PMessage]:
        """从 reader 接收消息"""
        try:
            length_data = await reader.read(4)
            if not length_data:
                return None
            
            length = int.from_bytes(length_data, 'big')
            data = await reader.readexactly(length)
            return P2PMessage.from_bytes(data)
        except Exception:
            return None
    
    # ==================== 工具方法 ====================
    
    async def send_heartbeat(self):
        """发送心跳"""
        message = P2PMessage(
            msg_type=MessageType.HEARTBEAT,
            sender_id=self.peer_id,
            payload={"timestamp": datetime.utcnow().isoformat()}
        )
        
        async with self._lock:
            for conn in self._connections.values():
                try:
                    await conn.send(message)
                except Exception:
                    pass
    
    def get_status(self) -> dict:
        """获取网络状态"""
        return {
            "peer_id": self.peer_id,
            "host": self.host,
            "port": self.port,
            "connected_peers": len(self._connections),
            "running": self._running
        }
