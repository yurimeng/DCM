"""
F14: QUIC Transport

推理数据的可靠传输层，基于 HTTP/3 (QUIC)
- 推理请求管理
- Streaming 结果收集
- result_hash 计算
"""

from .models import (
    # 数据类
    InferenceRequest,
    InferenceResult,
    InferenceSession,
    StreamingToken,
    # 枚举
    InferenceStatus,
    ConnectionState,
    # 配置
    QUICConfig,
    QUICMetrics,
)
from .quic_service import QUICService, quic_service

__all__ = [
    # 数据类
    "InferenceRequest",
    "InferenceResult",
    "InferenceSession",
    "StreamingToken",
    # 枚举
    "InferenceStatus",
    "ConnectionState",
    # 配置
    "QUICConfig",
    "QUICMetrics",
    # 服务
    "QUICService",
    "quic_service",
]
