"""
DCM - Decentralized Compute Market
Services Package
"""

from .escrow import EscrowService, escrow_service
from .matching import MatchingService, matching_service
from .verification import VerificationService, verification_service
from .retry import RetryService, retry_service, FailureType
from .stake import StakeService, stake_service

# Sprint 8: Job Queue (与 Match Engine 解耦)
from .queue import JobQueueService, QueueStats
from .queue.in_memory_queue import (
    InMemoryJobQueue, 
    get_job_queue, 
    reset_job_queue
)

# DCM v3.2: Job Config
from .job_config import JobConfig, get_job_config, reload_job_config

__all__ = [
    # Core
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
    # Queue
    "JobQueueService",
    "QueueStats",
    "InMemoryJobQueue",
    "get_job_queue",
    "reset_job_queue",
    # Job Config (DCM v3.2)
    "JobConfig",
    "get_job_config",
    "reload_job_config",
]

# Sprint 5: 链上服务
from .escrow_chain import chain_escrow_service
from .stake_chain import chain_stake_service

# Sprint 6: 双账本同步
from .chain_sync import chain_sync_service, ChainSyncService
