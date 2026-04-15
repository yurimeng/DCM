"""
Models - DCM v3.2
导出所有模型
"""

# Database models (for SQLAlchemy)
from .db_models import (
    JobDB, NodeDB, MatchDB, EscrowDB,
    StakeRecordDB, DisputeDB, AppealDB,
    WalletAccountDB, WalletTransactionDB,
    UserDB, UserSessionDB,
    JobStatusDB, NodeStatusDB, EscrowStatusDB, NodeTierDB,
)

# Job models
from .job import Job, JobStatus, JobCreate, JobResponse, JobQuery

# Cluster models (v3.2 with Pre-Lock)
# 注意: Cluster 是新的核心单元，Slot 作为别名保留以兼容现有代码
from .cluster import (
    # 核心类
    Cluster, ClusterStatus,
    LockType, JobSet, ClusterLock,
    ModelInfo, CapacityInfo, PricingInfo, PerformanceInfo,
    ClusterCreate, ClusterResponse,
    # Slot 别名 (兼容)
    Slot, SlotStatus, SlotLock,
    SlotCreate, SlotResponse,
)

# Match models
from .match import Match, MatchCreate, MatchResponse

# Node models
from .node import Node, NodeStatus, NodeTier, NodeCreate, NodeResponse, NodePollResponse, NodeResultSubmit

# Worker models
from .worker import Worker, WorkerStatus, WorkerResponse

# Runtime models
from .runtime import Runtime, RuntimeType, RuntimeStatus

# OpenAI Compatible models (DCM v3.2)
from .job_create_openai import JobCreateOpenAI, Message

# Escrow models
from .escrow import Escrow, EscrowStatus, SettlementRequest

# User models
from .user import (
    User, UserCreate, UserResponse, UserLogin, AuthResponse,
    AuthProvider, UserRole, UserStatus, NodeReputationBinding,
)

__all__ = [
    # Database Models
    "JobDB",
    "NodeDB",
    "MatchDB",
    "EscrowDB",
    "StakeRecordDB",
    "DisputeDB",
    "AppealDB",
    "WalletAccountDB",
    "WalletTransactionDB",
    "JobStatusDB",
    "NodeStatusDB",
    "EscrowStatusDB",
    "NodeTierDB",
    # Job
    "Job",
    "JobStatus", 
    "JobCreate",
    "JobResponse",
    "JobQuery",
    # Cluster (新核心单元)
    "Cluster",
    "ClusterStatus",
    "LockType",
    "JobSet",
    "ClusterLock",
    "ModelInfo",
    "CapacityInfo",
    "PricingInfo",
    "PerformanceInfo",
    "ClusterCreate",
    "ClusterResponse",
    # Slot 别名 (兼容)
    "Slot",
    "SlotStatus",
    "SlotLock",
    "SlotCreate",
    "SlotResponse",
    # Match
    "Match",
    "MatchCreate",
    "MatchResponse",
    # Node
    "Node",
    "NodeStatus",
    "NodeTier",
    "NodeCreate",
    "NodeResponse",
    "NodePollResponse",
    "NodeResultSubmit",
    # Worker
    "Worker",
    "WorkerStatus",
    "WorkerResponse",
    # Runtime
    "Runtime",
    "RuntimeType",
    "RuntimeStatus",
    # OpenAI Compatible
    "JobCreateOpenAI",
    "Message",
    # Escrow
    "Escrow",
    "EscrowStatus",
    "SettlementRequest",
    # User
    "User",
    "UserCreate",
    "UserResponse",
    "UserLogin",
    "AuthResponse",
    "AuthProvider",
    "UserRole",
    "UserStatus",
    "NodeReputationBinding",
]
