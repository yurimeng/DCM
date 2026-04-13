"""
F13: Core P2P Network

Core Cluster 3节点间的 P2P 通信层
- P2PNetwork: 底层 P2P 协议实现
- P2PService: 高层 P2P 服务
- gossipsub: 状态广播
- Relay: 连接兜底
"""

from .models import (
    # 数据类
    PeerInfo,
    P2PMessage,
    JobUpdate,
    NodeState,
    # 配置
    P2PConfig,
    P2PMetrics,
    # 枚举
    ConnectionStatus,
    Topics,
)
from .p2p_service import P2PService, p2p_service
from .network_protocol import P2PNetwork, P2PMessage as NetworkMessage, MessageType

__all__ = [
    # 数据类
    "PeerInfo",
    "P2PMessage",
    "JobUpdate",
    "NodeState",
    # 配置
    "P2PConfig",
    "P2PMetrics",
    # 枚举
    "ConnectionStatus",
    "Topics",
    # 服务
    "P2PService",
    "p2p_service",
    # 网络协议
    "P2PNetwork",
    "NetworkMessage",
    "MessageType",
]
