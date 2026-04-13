"""
Core Cluster Models
F9: Core Cluster
"""

from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional
import uuid


class CoreNodeStatus(str, Enum):
    """Core 节点状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class RoutingStrategy(str, Enum):
    """路由策略"""
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LEAST_CONNECTIONS = "least_connections"


@dataclass
class CoreNode:
    """Core 节点"""
    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    address: str = ""
    port: int = 8000
    weight: int = 1
    status: CoreNodeStatus = CoreNodeStatus.OFFLINE
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    
    # 监控指标
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    active_connections: int = 0
    
    # 健康状态
    latency_ms: float = 0.0
    healthy: bool = True
    consecutive_failures: int = 0
    
    @property
    def endpoint(self) -> str:
        return f"http://{self.address}:{self.port}"
    
    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "address": self.address,
            "port": self.port,
            "weight": self.weight,
            "status": self.status.value,
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "active_connections": self.active_connections,
            "last_heartbeat": self.last_heartbeat.isoformat(),
        }


@dataclass
class ClusterConfig:
    """集群配置"""
    min_nodes: int = 3
    max_nodes: int = 5
    quorum: int = 2  # 多数节点数
    
    # 健康检查
    heartbeat_interval_sec: int = 10
    heartbeat_timeout_sec: int = 30
    max_consecutive_failures: int = 3
    
    # 路由策略
    routing_strategy: RoutingStrategy = RoutingStrategy.ROUND_ROBIN
    
    # P2P 同步
    sync_interval_sec: int = 10
    sync_timeout_sec: int = 5
    
    # 链上账本
    chain_sync_enabled: bool = True
    chain_sync_interval_sec: int = 60


@dataclass
class ClusterMetrics:
    """集群指标"""
    total_nodes: int = 0
    healthy_nodes: int = 0
    online_nodes: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    avg_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # 计算属性
    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests * 100
    
    @property
    def available(self) -> bool:
        return self.online_nodes >= 2  # 至少 2 个节点可用
