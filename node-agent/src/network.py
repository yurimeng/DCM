"""
Network Layer - 多协议支持
基于 F16-Runtime-Adapter-Layer 和网络状态矩阵设计

支持的网络类型:
- HTTPS: 标准 REST API
- WSS: WebSocket 实时推送
- P2P: 点对点通信 (gossipsub)
- Relay: 中继穿透 (circuit relay)
"""

import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
import threading
import requests

logger = logging.getLogger(__name__)


class NetworkType(str, Enum):
    """网络类型"""
    HTTPS = "https"           # 标准 HTTPS
    WSS = "wss"               # WebSocket
    P2P = "p2p"               # P2P 直连
    RELAY = "relay"           # 中继


class NetworkState(str, Enum):
    """网络状态"""
    ONLINE = "online"          # 正常连接
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
    wss_endpoint: str = "wss://dcm-api-p00a.onrender.com/ws"
    p2p_bootstrap: str = "/dns4/dcm-p2p.example.com/tcp/4001"
    relay_server: str = "/ip4/relay.example.com/tcp/4001"


class NetworkAdapter:
    """
    网络适配器 - 统一处理不同网络协议
    
    设计目标:
    1. 自动检测最优网络路径
    2. 支持网络切换 (HTTPS → P2P → Relay)
    3. 网络降级处理
    4. 自动重连
    """
    
    def __init__(self, config: Optional[NetworkConfig] = None):
        self.config = config or NetworkConfig()
        self.current_state = NetworkState.ONLINE
        self.current_type = self.config.primary
        self._lock = threading.Lock()
        self._callbacks: Dict[str, Callable] = {}
        
        # 连接状态
        self._connected = False
        self._last_heartbeat = 0
        self._failure_count = 0
    
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
        """建立连接"""
        with self._lock:
            if self.current_type == NetworkType.HTTPS:
                return self._connect_https()
            elif self.current_type == NetworkType.WSS:
                return self._connect_wss()
            elif self.current_type == NetworkType.P2P:
                return self._connect_p2p()
            elif self.current_type == NetworkType.RELAY:
                return self._connect_relay()
            return False
    
    def disconnect(self):
        """断开连接"""
        with self._lock:
            self._connected = False
            self.current_state = NetworkState.OFFLINE
            logger.info(f"网络断开: {self.current_type}")
    
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
                self._failure_count = 0
                logger.info("✅ HTTPS 连接成功")
                return True
        except Exception as e:
            logger.warning(f"HTTPS 连接失败: {e}")
        
        self._handle_connection_failure()
        return False
    
    def _connect_wss(self) -> bool:
        """WebSocket 连接 (预留)"""
        # TODO: 实现 WebSocket 连接
        logger.warning("WebSocket 连接尚未实现，使用 HTTPS 降级")
        return self._connect_https()
    
    def _connect_p2p(self) -> bool:
        """P2P 连接 (预留)"""
        # TODO: 实现 P2P 连接 (libp2p)
        logger.warning("P2P 连接尚未实现，使用 Relay 降级")
        return self._connect_relay()
    
    def _connect_relay(self) -> bool:
        """Relay 连接 (预留)"""
        # TODO: 实现 Relay 连接 (circuit relay)
        logger.warning("Relay 连接尚未实现，使用 HTTPS 降级")
        return self._connect_https()
    
    def _handle_connection_failure(self):
        """处理连接失败"""
        self._failure_count += 1
        self._connected = False
        
        if not self.config.fallback_enabled:
            self.current_state = NetworkState.OFFLINE
            return
        
        # 降级策略: HTTPS → P2P → Relay → OFFLINE
        if self.current_type == NetworkType.HTTPS:
            logger.warning("HTTPS 失败，尝试 P2P...")
            self.current_type = NetworkType.P2P
            self.current_state = NetworkState.DEGRADED
        elif self.current_type == NetworkType.P2P:
            logger.warning("P2P 失败，尝试 Relay...")
            self.current_type = NetworkType.RELAY
            self.current_state = NetworkState.P2P_RELAY
        else:
            logger.error("所有网络路径失败")
            self.current_state = NetworkState.OFFLINE
    
    # ==================== 请求处理 ====================
    
    def request(
        self,
        method: str,
        path: str,
        data: Optional[Dict] = None,
        timeout: Optional[int] = None
    ) -> Optional[Dict]:
        """
        发送请求
        
        Args:
            method: HTTP 方法 (GET/POST/PUT/DELETE)
            path: 请求路径
            data: 请求数据
            timeout: 超时时间
            
        Returns:
            响应数据或 None
        """
        if not self._connected:
            if not self.connect():
                return None
        
        url = f"{self.config.https_endpoint}{path}"
        timeout = timeout or self.config.timeout_seconds
        
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
            self._handle_connection_failure()
            return None
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"请求失败: {e}")
            self._handle_connection_failure()
            return None
    
    def get(self, path: str, timeout: Optional[int] = None) -> Optional[Dict]:
        """GET 请求"""
        return self.request("GET", path, timeout=timeout)
    
    def post(self, path: str, data: Dict, timeout: Optional[int] = None) -> Optional[Dict]:
        """POST 请求"""
        return self.request("POST", path, data, timeout)
    
    # ==================== 健康检查 ====================
    
    def health_check(self) -> bool:
        """健康检查"""
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
            NetworkState.P2P_DIRECT,
            NetworkState.P2P_RELAY
        ]


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
        return ""
    
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
