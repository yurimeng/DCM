"""
F13: Core P2P Network - 数据模型

Core Cluster 3节点间的 P2P 通信层模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ConnectionStatus(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RELAYED = "relayed"


@dataclass
class PeerInfo:
    """P2P 节点信息"""
    peer_id: str
    addresses: List[str] = field(default_factory=list)
    is_relay: bool = False
    last_seen: datetime = field(default_factory=datetime.utcnow)
    latency_ms: float = 0.0
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    retry_count: int = 0
    relay_node: Optional[str] = None  # 如果通过 relay 连接，记录 relay 节点

    @property
    def is_connected(self) -> bool:
        return self.status in (ConnectionStatus.CONNECTED, ConnectionStatus.RELAYED)

    @property
    def idle_time_sec(self) -> float:
        return (datetime.utcnow() - self.last_seen).total_seconds()


@dataclass
class P2PMessage:
    """P2P 消息"""
    topic: str
    sender_id: str
    data: dict
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_ms: int = 5000  # 默认 5 秒


@dataclass
class JobUpdate:
    """Job 更新消息 (gossipsub topic: job_update)"""
    sender_id: str
    data: dict
    topic: str = "job_update"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_ms: int = 5000
    
    def __post_init__(self):
        self.data.setdefault("job_id", "")
        self.data.setdefault("status", "")
        self.data.setdefault("match_id", "")


@dataclass
class NodeState:
    """节点状态消息 (gossipsub topic: node_state)"""
    sender_id: str
    data: dict
    topic: str = "node_state"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_ms: int = 5000


@dataclass
class P2PConfig:
    """P2P 配置"""
    # 连接配置
    listen_addresses: List[str] = field(default_factory=lambda: ["/ip4/0.0.0.0/tcp/4001"])
    bootstrap_nodes: List[str] = field(default_factory=list)  # ["/ip4/x.x.x.x/tcp/4001/p2p/Qm..."]
    
    # 行为配置
    heartbeat_interval_sec: int = 30
    node_timeout_sec: int = 90
    max_retry_count: int = 5
    relay_enabled: bool = True
    
    # pub/sub 配置
    topics: List[str] = field(default_factory=lambda: ["job_update", "node_state"])
    message_ttl_ms: int = 5000
    
    # 连接限制
    max_peers: int = 10
    max_relay_connections: int = 100


@dataclass
class P2PMetrics:
    """P2P 指标"""
    connections_established: int = 0
    connections_failed: int = 0
    direct_connections: int = 0
    relayed_connections: int = 0
    direct_fallback_count: int = 0
    messages_sent: int = 0
    messages_received: int = 0


# 预定义 topic
class Topics:
    JOB_UPDATE = "job_update"
    NODE_STATE = "node_state"
    MATCH_RESULT = "match_result"
    ESCROW_SYNC = "escrow_sync"
