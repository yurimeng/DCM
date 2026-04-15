"""
Internal API 模块

按功能拆分为多个子模块:
- operations: 运维接口 (健康检查、配置)
- matching: 撮合/验证/结算接口
- reconciliation: 对账接口
- admin: 管理接口 (Stake、统计、数据库)
- debug: 调试接口
"""

from .operations import router as operations_router
from .matching import router as matching_router
from .reconciliation import router as reconciliation_router
from .admin import router as admin_router
from .debug import router as debug_router

__all__ = [
    "operations_router",
    "matching_router",
    "reconciliation_router",
    "admin_router",
    "debug_router",
]
