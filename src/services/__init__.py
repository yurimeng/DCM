"""
DCM - Decentralized Compute Market
Services Package
"""

from .escrow import EscrowService, escrow_service
from .matching import MatchingService, matching_service
from .verification import VerificationService, verification_service
from .retry import RetryService, retry_service, FailureType
from .stake import StakeService, stake_service

__all__ = [
    "EscrowService",
    "escrow_service",
    "MatchingService",
    "matching_service",
    "VerificationService",
    "verification_service",
    "RetryService",
    "retry_service",
    "FailureType",
    "StakeService",
    "stake_service",
]

# Sprint 5: 链上服务
from .escrow_chain import chain_escrow_service
from .stake_chain import chain_stake_service

# Sprint 6: 双账本同步
from .chain_sync import chain_sync_service, ChainSyncService
