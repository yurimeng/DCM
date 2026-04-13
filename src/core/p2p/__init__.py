"""
F13: Core P2P Network

Core Cluster 3节点间的 P2P 通信层
- 节点发现 (libp2p bootstrap)
- 状态广播 (gossipsub)
- Relay 兜底 (circuit relay v2)
"""

from .models import (
    # 数据类
    PeerInfo,
    P2PMessage,
    JobUpdate,
    NodeState,
    P2PConfig,
    P2PMetrics,
    # 枚举
    ConnectionStatus,
    # 常量
    Topics,
)
from .p2p_service import P2PService, p2p_service

__all__ = [
    # 数据类
    "PeerInfo",
    "P2PMessage",
    "JobUpdate",
    "NodeState",
    "P2PConfig",
    "P2PMetrics",
    # 枚举
    "ConnectionStatus",
    # 常量
    "Topics",
    # 服务
    "P2PService",
    "p2p_service",
]
