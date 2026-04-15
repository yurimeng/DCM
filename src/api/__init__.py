"""
DCM - Decentralized Compute Market
API Package
"""

from .jobs import router as jobs_router
from .nodes import router as nodes_router
from .users import router as users_router
from .internal_agg import router as internal_router  # 聚合入口
from .disputes import router as disputes_router
from .wallet import router as wallet_router
from .p2p import router as p2p_router
from .quic import router as quic_router
from .relay import router as relay_router
from .core import router as core_router
from .scaler import router as scaler_router
from .worker_pool import router as worker_pool_router

__all__ = [
    "jobs_router",
    "nodes_router",
    "users_router",
    "internal_router",
    "disputes_router",
    "wallet_router",
    "p2p_router",
    "quic_router",
    "relay_router",
    "core_router",
    "scaler_router",
    "worker_pool_router",
]
