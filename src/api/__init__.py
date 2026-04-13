"""
DCM - Decentralized Compute Market
API Package
"""

from .jobs import router as jobs_router
from .nodes import router as nodes_router
from .internal import router as internal_router
from .disputes import router as disputes_router
from .wallet import router as wallet_router
from .p2p import router as p2p_router

__all__ = [
    "jobs_router",
    "nodes_router",
    "internal_router",
    "disputes_router",
    "wallet_router",
    "p2p_router",
]
