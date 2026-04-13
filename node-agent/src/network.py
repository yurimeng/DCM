"""
Network Layer - 多协议支持
基于 F16-Runtime-Adapter-Layer 和网络状态矩阵设计

支持的网络类型:
- HTTPS: 标准 REST API
- QUIC: 基于 UDP 的 QUIC 协议 (低延迟)
- P2P: 点对点通信 (gossipsub)
- Relay: 中继穿透 (circuit relay)
"""

import time
import asyncio
import logging
import struct
import hashlib
from enum import Enum
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from threading import Thread, Lock, Event
import requests

logger = logging.getLogger(__name__)

try:
    from aioquic.asyncio import connect, serve, QuicConnectionProtocol
    from aioquic.asyncio.server import QuicServer
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.events import QuicEvent, StreamDataReceived, HandshakeCompleted
    from aioquic.h3.connection import H3Connection
    from aioquic.h3.events import H3Event, HeadersReceived, DataReceived
    AIOQUIC_AVAILABLE = True
except ImportError as e:
    AIOQUIC_AVAILABLE = False
    import sys
    print(f"WARNING: aioquic 导入失败: {e}", file=sys.stderr)


class NetworkType(str, Enum):
    """网络类型"""
    HTTPS = "https"           # 标准 HTTPS
    QUIC = "quic"             # QUIC 协议
    WSS = "wss"               # WebSocket
    P2P = "p2p"               # P2P 直连
    RELAY = "relay"           # 中继


class NetworkState(str, Enum):
    """网络状态"""
    ONLINE = "online"          # 正常连接
    QUIC_CONNECTED = "quic_connected"  # QUIC 已连接
    P2P_DIRECT = "p2p_direct"  # P2P 直连
    P2P_RELAY = "p2p_relay"   # P2P 中继
    DEGRADED = "degraded"      # 降级模式
    OFFLINE = "offline"        # 断开连接
    TIMEOUT = "timeout"        # 超时


@dataclass
class NetworkConfig:
    """网络配置"""
    primary: NetworkType = NetworkType.HTTPS
    fallback_enabled: bool = True
    timeout_seconds: int = 30
    retry_count: int = 3
    retry_interval: int = 5
    
    # 各协议端点
    https_endpoint: str = "https://dcm-api-p00a.onrender.com"
    quic_endpoint: str = "dcm-api-p00a.onrender.com"
    quic_port: int = 8443
    wss_endpoint: str = "wss://dcm-api-p00a.onrender.com/ws"
    p2p_bootstrap: str = "/dns4/dcm-p2p.example.com/tcp/4001"
    relay_server: str = "/ip4/relay.example.com/tcp/4001"
    
    # QUIC 配置
    quic_enabled: bool = True
    quic_alpn: List[str] = field(default_factory=lambda: ["h3", "dcm/1"])
    
    # Relay 配置
    relay_enabled: bool = True
    relay_port: int = 4001


class RelayConnection:
    """
    Relay 中继连接
    
    实现 circuit relay 协议:
    1. Node 向 Relay Server 注册
    2. Relay 分配 relay_addr
    3. Client 通过 Relay 与 Node 建立连接
    """
    
    def __init__(self, config: NetworkConfig):
        self.config = config
        self.relay_addr: Optional[str] = None
        self.connected = False
        self.peer_id: Optional[str] = None
        
    def generate_peer_id(self) -> str:
        """生成 Peer ID"""
        timestamp = str(time.time()).encode()
        return hashlib.sha256(timestamp).hexdigest()[:16]
    
    def connect(self) -> bool:
        """
        连接 Relay Server
        
        流程:
        1. 建立 TCP 连接到 Relay Server
        2. 发送 CONNECT 请求
        3. 接收分配的 relay_addr
        """
        try:
            import socket
            
            # 解析 Relay 地址
            relay_host = self.config.relay_server.split("/")[2] if "/" in self.config.relay_server else self.config.relay_server
            relay_port = self.config.relay_port
            
            logger.info(f"🔗 连接 Relay Server: {relay_host}:{relay_port}")
            
            # 创建 TCP socket (模拟，实际使用 libp2p)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((relay_host, relay_port))
            
            # 生成 Peer ID
            self.peer_id = self.generate_peer_id()
            
            # 发送 CONNECT 握手
            handshake = {
                "type": "connect",
                "peer_id": self.peer_id,
                "protocol": "circuit-relay",
                "version": "1.0"
            }
            handshake_data = str(handshake).encode()
            sock.sendall(len(handshake_data).to_bytes(4, 'big') + handshake_data)
            
            # 接收响应
            resp_len = int.from_bytes(sock.recv(4), 'big')
            resp_data = sock.recv(resp_len).decode()
            
            import json
            resp = json.loads(resp_data)
            
            if resp.get("status") == "connected":
                self.relay_addr = resp.get("relay_addr", f"/ipfs/{self.peer_id}")
                self.connected = True
                sock.close()
                logger.info(f"✅ Relay 连接成功: {self.relay_addr}")
                return True
            
            sock.close()
            
        except Exception as e:
            logger.warning(f"Relay 连接失败: {e}")
        
        return False
    
    def disconnect(self):
        """断开 Relay 连接"""
        self.connected = False
        self.relay_addr = None
        logger.info("Relay 连接已断开")
    
    def send_via_relay(self, data: Dict, target_peer: str) -> Optional[Dict]:
        """
        通过 Relay 发送数据
        
        Args:
            data: 要发送的数据
            target_peer: 目标节点 Peer ID
        """
        if not self.connected:
            return None
        
        try:
            # 模拟通过 Relay 发送数据
            # 实际实现需要完整的 libp2p circuit relay 协议
            logger.debug(f"Relay 发送数据到 {target_peer}")
            return {"status": "sent", "relay_addr": self.relay_addr}
        except Exception as e:
            logger.error(f"Relay 发送失败: {e}")
            return None


class QUICConnection:
    """
    QUIC 连接管理
    
    基于 aioquic 实现:
    1. HTTP/3 协议栈
    2. 0-RTT 快速恢复
    3. 连接迁移
    """
    
    def __init__(self, config: NetworkConfig):
        self.config = config
        self.connected = False
        self._protocol: Optional[QuicConnectionProtocol] = None
        self._h3: Optional[H3Connection] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._stop_event = Event()
        
    def _create_config(self) -> 'QuicConfiguration':
        """创建 QUIC 配置"""
        quic_config = QuicConfiguration(
            alpn_protocols=self.config.quic_alpn,
            is_client=True,
            max_datagram_frame_size=65535,
        )
        quic_config.verify_mode = False  # MVP 阶段不验证证书
        return quic_config
    
    async def _connect_async(self) -> bool:
        """异步连接"""
        if not AIOQUIC_AVAILABLE:
            logger.warning("aioquic 不可用")
            return False
        
        try:
            host = self.config.quic_endpoint
            port = self.config.quic_port
            
            logger.info(f"🔗 QUIC 连接: {host}:{port}")
            
            async with connect(
                host,
                port,
                configuration=self._create_config(),
                create_protocol=QuicConnectionProtocol
            ) as protocol:
                self._protocol = protocol
                self.connected = True
                
                # 获取 H3 连接
                self._h3 = H3Connection(self._protocol._quic)
                
                logger.info("✅ QUIC 连接成功 (HTTP/3)")
                
                # 保持连接直到停止
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.warning(f"QUIC 连接失败: {e}")
            self.connected = False
            return False
        
        return False
    
    def connect(self) -> bool:
        """同步连接 (启动后台线程运行异步代码)"""
        if not self.config.quic_enabled or not AIOQUIC_AVAILABLE:
            logger.info("QUIC 未启用，使用 HTTPS")
            return False
        
        if self.connected:
            return True
        
        self._stop_event.clear()
        
        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._connect_async())
            finally:
                loop.close()
        
        self._thread = Thread(target=run_loop, daemon=True)
        self._thread.start()
        
        # 等待连接建立
        for _ in range(10):
            time.sleep(0.5)
            if self.connected:
                return True
        
        return False
    
    def disconnect(self):
        """断开 QUIC 连接"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self.connected = False
        self._protocol = None
        self._h3 = None
        logger.info("QUIC 连接已断开")
    
    async def _request_async(self, method: str, path: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """异步发送请求"""
        if not self.connected or not self._protocol:
            return None
        
        try:
            # 构建 HTTP/3 请求
            headers = [
                (b":method", method.encode()),
                (b":scheme", b"https"),
                (b":authority", self.config.quic_endpoint.encode()),
                (b":path", path.encode()),
            ]
            
            # 发送请求
            stream_id = self._protocol._quic.get_next_available_stream_id()
            
            # 发送 HEADERS
            self._h3.send_headers(stream_id, headers)
            
            # 发送 DATA (如果有)
            if data:
                body = str(data).encode()
                self._h3.send_data(stream_id, body, end_stream=True)
            else:
                self._h3.transmit()
            
            # 等待响应
            # 实际实现需要完整的异步响应处理
            
            return {"status": "quic_ok"}
            
        except Exception as e:
            logger.error(f"QUIC 请求失败: {e}")
            return None
    
    def request(self, method: str, path: str, data: Optional[Dict] = None, timeout: int = 30) -> Optional[Dict]:
        """同步请求"""
        if not self.connected:
            return None
        
        try:
            # 使用线程运行异步代码
            future = asyncio.run_coroutine_threadsafe(
                self._request_async(method, path, data),
                asyncio.get_event_loop() if self._loop else asyncio.new_event_loop()
            )
            return future.result(timeout=timeout)
        except Exception as e:
            logger.warning(f"QUIC 请求异常: {e}")
            return None
    
    def get(self, path: str) -> Optional[Dict]:
        """GET 请求"""
        return self.request("GET", path)
    
    def post(self, path: str, data: Dict) -> Optional[Dict]:
        """POST 请求"""
        return self.request("POST", path, data)


class NetworkAdapter:
    """
    网络适配器 - 统一处理不同网络协议
    
    设计目标:
    1. 自动检测最优网络路径 (QUIC > HTTPS > Relay)
    2. 支持网络切换
    3. 网络降级处理
    4. NAT 穿透支持
    """
    
    def __init__(self, config: Optional[NetworkConfig] = None):
        self.config = config or NetworkConfig()
        self.current_state = NetworkState.ONLINE
        self.current_type = self.config.primary
        self._lock = Lock()
        self._callbacks: Dict[str, Callable] = {}
        
        # 连接状态
        self._connected = False
        self._last_heartbeat = 0
        self._failure_count = 0
        
        # 各协议连接
        self._quic: Optional[QUICConnection] = None
        self._relay: Optional[RelayConnection] = None
        
        # 初始化连接
        if self.config.quic_enabled:
            self._quic = QUICConnection(self.config)
        if self.config.relay_enabled:
            self._relay = RelayConnection(self.config)
    
    def register_callback(self, event: str, callback: Callable):
        """注册网络事件回调"""
        self._callbacks[event] = callback
    
    def _notify(self, event: str, data: Any = None):
        """触发网络事件"""
        if event in self._callbacks:
            try:
                self._callbacks[event](self.current_state, data)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    # ==================== 连接管理 ====================
    
    def connect(self) -> bool:
        """建立连接 (智能选择最优协议)"""
        with self._lock:
            # 优先尝试 QUIC
            if self.current_type == NetworkType.QUIC and self._quic:
                if self._connect_quic():
                    return True
                # QUIC 失败，降级到 HTTPS
                self.current_type = NetworkType.HTTPS
            
            # HTTPS
            if self.current_type == NetworkType.HTTPS:
                if self._connect_https():
                    return True
            
            # Relay (最后降级)
            if self.config.relay_enabled and self._relay:
                if self._connect_relay():
                    self.current_state = NetworkState.P2P_RELAY
                    return True
            
            self.current_state = NetworkState.OFFLINE
            return False
    
    def disconnect(self):
        """断开所有连接"""
        with self._lock:
            self._connected = False
            self.current_state = NetworkState.OFFLINE
            if self._quic:
                self._quic.disconnect()
            if self._relay:
                self._relay.disconnect()
            logger.info("所有网络连接已断开")
    
    def _connect_https(self) -> bool:
        """HTTPS 连接"""
        try:
            resp = requests.get(
                f"{self.config.https_endpoint}/health",
                timeout=5
            )
            if resp.status_code == 200:
                self._connected = True
                self.current_state = NetworkState.ONLINE
                self.current_type = NetworkType.HTTPS
                self._failure_count = 0
                logger.info("✅ HTTPS 连接成功")
                return True
        except Exception as e:
            logger.warning(f"HTTPS 连接失败: {e}")
        
        return False
    
    def _connect_quic(self) -> bool:
        """QUIC 连接"""
        if not self._quic:
            return False
        
        if self._quic.connect():
            self._connected = True
            self.current_state = NetworkState.QUIC_CONNECTED
            self.current_type = NetworkType.QUIC
            self._failure_count = 0
            return True
        
        return False
    
    def _connect_relay(self) -> bool:
        """Relay 连接"""
        if not self._relay:
            return False
        
        if self._relay.connect():
            self._connected = True
            return True
        
        return False
    
    # ==================== 请求处理 ====================
    
    def request(
        self,
        method: str,
        path: str,
        data: Optional[Dict] = None,
        timeout: Optional[int] = None
    ) -> Optional[Dict]:
        """
        发送请求 (自动选择最优协议)
        """
        if not self._connected:
            if not self.connect():
                return None
        
        timeout = timeout or self.config.timeout_seconds
        
        # QUIC 请求
        if self.current_type == NetworkType.QUIC and self._quic and self._quic.connected:
            result = self._quic.request(method, path, data, timeout)
            if result:
                return result
            # QUIC 失败，切换到 HTTPS
            self.current_type = NetworkType.HTTPS
        
        # HTTPS 请求
        if self.current_type == NetworkType.HTTPS:
            return self._request_https(method, path, data, timeout)
        
        # Relay 请求
        if self.current_type == NetworkType.RELAY and self._relay and self._relay.connected:
            return self._request_relay(method, path, data)
        
        return None
    
    def _request_https(self, method: str, path: str, data: Optional[Dict], timeout: int) -> Optional[Dict]:
        """HTTPS 请求"""
        url = f"{self.config.https_endpoint}{path}"
        
        try:
            if method.upper() == "GET":
                resp = requests.get(url, timeout=timeout)
            elif method.upper() == "POST":
                resp = requests.post(url, json=data, timeout=timeout)
            elif method.upper() == "PUT":
                resp = requests.put(url, json=data, timeout=timeout)
            elif method.upper() == "DELETE":
                resp = requests.delete(url, timeout=timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            resp.raise_for_status()
            self._last_heartbeat = time.time()
            self._failure_count = 0
            self.current_state = NetworkState.ONLINE
            
            return resp.json() if resp.content else {}
            
        except requests.exceptions.Timeout:
            logger.warning(f"请求超时: {path}")
            self.current_state = NetworkState.TIMEOUT
            return None
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"请求失败: {e}")
            return None
    
    def _request_relay(self, method: str, path: str, data: Optional[Dict]) -> Optional[Dict]:
        """Relay 请求"""
        if not self._relay:
            return None
        
        # 从 path 提取目标 peer
        target_peer = "api-server"
        return self._relay.send_via_relay({
            "method": method,
            "path": path,
            "data": data
        }, target_peer)
    
    def get(self, path: str, timeout: Optional[int] = None) -> Optional[Dict]:
        """GET 请求"""
        return self.request("GET", path, timeout=timeout)
    
    def post(self, path: str, data: Dict, timeout: Optional[int] = None) -> Optional[Dict]:
        """POST 请求"""
        return self.request("POST", path, data, timeout)
    
    # ==================== 网络状态 ====================
    
    def health_check(self) -> bool:
        """健康检查"""
        if self.current_type == NetworkType.QUIC and self._quic:
            return self._quic.connected
        return self._connected and self.request("GET", "/health") is not None
    
    def get_state(self) -> NetworkState:
        """获取当前网络状态"""
        return self.current_state
    
    def get_type(self) -> NetworkType:
        """获取当前网络类型"""
        return self.current_type
    
    def is_healthy(self) -> bool:
        """检查是否健康"""
        return self.current_state in [
            NetworkState.ONLINE,
            NetworkState.QUIC_CONNECTED,
            NetworkState.P2P_DIRECT,
            NetworkState.P2P_RELAY
        ]
    
    def switch_to_quic(self) -> bool:
        """切换到 QUIC"""
        if not self.config.quic_enabled or not AIOQUIC_AVAILABLE:
            logger.warning("QUIC 不可用")
            return False
        
        if self._connect_quic():
            logger.info("✅ 已切换到 QUIC")
            return True
        return False
    
    def switch_to_https(self):
        """切换到 HTTPS"""
        self.current_type = NetworkType.HTTPS
        if self._connect_https():
            logger.info("✅ 已切换到 HTTPS")
            return True
        return False
    
    def get_relay_addr(self) -> Optional[str]:
        """获取 Relay 地址 (供外部节点连接)"""
        if self._relay and self._relay.connected:
            return self._relay.relay_addr
        return None


class Invoke:
    """
    统一的 Invoke 结构 - 支持多网络协议
    
    网络感知字段:
    - network_type: 下发时使用的网络类型
    - connection_hints: 连接提示 (P2P peer ID, Relay 地址等)
    """
    
    def __init__(self, data: Optional[Dict] = None):
        self.execution_id: str = ""
        self.job_id: str = ""
        self.slot_id: str = ""
        self.model: Dict = {}
        self.input: Dict = {}
        self.generation: Dict = {}
        self.runtime: Dict = {}
        
        # 网络感知字段
        self.network_type: NetworkType = NetworkType.HTTPS
        self.connection_hints: Dict = {}
        
        if data:
            self.from_dict(data)
    
    def from_dict(self, data: Dict):
        """从字典加载"""
        self.execution_id = data.get("execution_id", "")
        self.job_id = data.get("job_id", "")
        self.slot_id = data.get("slot_id", "")
        self.model = data.get("model", {})
        self.input = data.get("input", {})
        self.generation = data.get("generation", {})
        self.runtime = data.get("runtime", {})
        
        # 网络类型
        net_type = data.get("network_type", "https")
        if isinstance(net_type, str):
            self.network_type = NetworkType(net_type.lower())
        
        self.connection_hints = data.get("connection_hints", {})
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "job_id": self.job_id,
            "slot_id": self.slot_id,
            "model": self.model,
            "input": self.input,
            "generation": self.generation,
            "runtime": self.runtime,
            "network_type": self.network_type.value,
            "connection_hints": self.connection_hints,
        }
    
    def get_prompt(self) -> str:
        """从 input 中提取 prompt"""
        messages = self.input.get("messages", [])
        for msg in messages:
            if msg.get("role") == "user":
                return msg.get("content", "")
        return self.input.get("prompt_raw", "")
    
    def get_model_name(self) -> str:
        """获取模型名称"""
        return self.model.get("name", "qwen2.5:7b")
    
    def get_max_tokens(self) -> int:
        """获取最大 token 数"""
        return self.generation.get("max_tokens", 100)


class Result:
    """
    统一的 Result 结构
    
    包含网络回传信息:
    - return_route: 返回路径 (direct/p2p/relay)
    - delivery_status: 投递状态
    """
    
    def __init__(
        self,
        execution_id: str = "",
        job_id: str = "",
        slot_id: str = "",
        status: str = "completed",
        output: Optional[Dict] = None,
        usage: Optional[Dict] = None,
        metrics: Optional[Dict] = None,
        error: Optional[str] = None
    ):
        self.execution_id = execution_id
        self.job_id = job_id
        self.slot_id = slot_id
        self.status = status
        self.output = output or {}
        self.usage = usage or {}
        self.metrics = metrics or {}
        self.error = error
        
        # 网络回传字段
        self.return_route: NetworkType = NetworkType.HTTPS
        self.delivery_status: str = "pending"
        self.delivered_at: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "execution_id": self.execution_id,
            "job_id": self.job_id,
            "slot_id": self.slot_id,
            "status": self.status,
            "output": self.output,
            "usage": self.usage,
            "metrics": self.metrics,
            "error": self.error,
            "return_route": self.return_route.value,
            "delivery_status": self.delivery_status,
        }
    
    def mark_delivered(self):
        """标记已投递"""
        self.delivery_status = "delivered"
        self.delivered_at = time.time()
