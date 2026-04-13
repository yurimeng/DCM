"""
F15: Relay Service - 数据模型

P2P Relay 兜底机制
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class RelayConnectionType(Enum):
    """Relay 连接类型"""
    DIRECT = "direct"           # 直连
    RELAYED = "relayed"         # 通过 Relay 中继


class RelayStatus(Enum):
    """Relay 状态"""
    DISABLED = "disabled"
    ENABLED = "enabled"
    ACTIVE = "active"           # 有活跃连接
    OVERLOADED = "overloaded"   # 负载过高


@dataclass
class RelayConnection:
    """Relay 连接"""
    connection_id: str
    source_peer_id: str
    target_peer_id: str
    relay_node: str              # 使用的 Relay 节点
    connection_type: RelayConnectionType
    
    # 带宽统计
    bytes_sent: int = 0
    bytes_received: int = 0
    
    # 时间戳
    established_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    
    # 状态
    active: bool = True
    
    @property
    def age_seconds(self) -> float:
        return (datetime.utcnow() - self.established_at).total_seconds()
    
    def update_activity(self):
        self.last_activity = datetime.utcnow()


@dataclass
class RelayNode:
    """Relay 节点 (Core 兼任)"""
    peer_id: str
    addresses: List[str]
    status: RelayStatus = RelayStatus.ENABLED
    
    # 带宽限制
    max_bandwidth_bps: int = 1 * 1024 * 1024 * 1024  # 1 Gbps
    current_bandwidth_bps: int = 0
    
    # 连接统计
    active_connections: int = 0
    total_connections: int = 0
    
    # 时间戳
    last_seen: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def bandwidth_usage_percent(self) -> float:
        if self.max_bandwidth_bps == 0:
            return 0
        return (self.current_bandwidth_bps / self.max_bandwidth_bps) * 100
    
    @property
    def is_available(self) -> bool:
        return self.status == RelayStatus.ENABLED and self.bandwidth_usage_percent < 90


@dataclass
class RelayConfig:
    """Relay 配置"""
    # 行为配置
    relay_enabled: bool = True
    max_connections_per_relay: int = 1000
    max_connections_per_worker: int = 50
    
    # 带宽限制 (bits/s)
    per_connection_limit_bps: int = 10 * 1024 * 1024      # 10 Mbps
    per_worker_limit_bps: int = 50 * 1024 * 1024         # 50 Mbps
    per_relay_total_limit_bps: int = 1024 * 1024 * 1024  # 1 Gbps
    
    # 超时配置
    connection_timeout_sec: int = 30
    idle_timeout_sec: int = 300
    
    # 策略
    prefer_direct: bool = True  # 优先直连
    auto_reconnect: bool = True


@dataclass
class RelayMetrics:
    """Relay 指标"""
    total_relay_requests: int = 0
    successful_relays: int = 0
    failed_relays: int = 0
    active_relay_connections: int = 0
    
    # 带宽统计
    total_bytes_relayed: int = 0
    current_bandwidth_bps: int = 0
    
    # 延迟统计
    avg_relay_latency_ms: float = 0.0
    
    # 降级统计
    direct_fallback_count: int = 0  # 直连失败的次数
