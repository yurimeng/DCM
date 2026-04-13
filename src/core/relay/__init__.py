"""
F15: Relay Service

P2P 直连的兜底机制

- Relay 节点管理 (Core 兼任)
- 带宽控制与限速
- 连接诊断与监控
"""

from .models import (
    # 枚举
    RelayConnectionType,
    RelayStatus,
    # 数据类
    RelayConnection,
    RelayNode,
    RelayConfig,
    RelayMetrics,
)
from .relay_service import RelayService, relay_service

__all__ = [
    # 枚举
    "RelayConnectionType",
    "RelayStatus",
    # 数据类
    "RelayConnection",
    "RelayNode",
    "RelayConfig",
    "RelayMetrics",
    # 服务
    "RelayService",
    "relay_service",
]
