"""
Database Models - SQLAlchemy ORM Models
来源: PRD 0.2 Section 4 & Function/F1-F8
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from ..database import Base
import enum


class JobStatusDB(str, enum.Enum):
    """Job 状态"""
    PENDING = "pending"
    MATCHED = "matched"
    PRE_LOCKED = "pre_locked"    # 预锁定中
    RESERVED = "reserved"        # 已预约
    DISPATCHED = "dispatched"    # 已分发
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatusDB(str, enum.Enum):
    """节点状态"""
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"
    LOCKED = "locked"


class EscrowStatusDB(str, enum.Enum):
    """Escrow 状态"""
    PENDING = "pending"     # 待锁定
    LOCKED = "locked"       # 已锁定，等待结算
    COMPLETED = "completed" # 已完成（等待自动转账）
    SETTLED = "settled"     # 已结算
    REFUNDED = "refunded"   # 已退款
    CANCELLED = "cancelled"  # 已取消


class NodeTierDB(str, enum.Enum):
    """Stake 分级"""
    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    DATA_CENTER = "datacenter"


class JobDB(Base):
    """Job 数据库模型"""
    __tablename__ = "jobs"
    
    job_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=True)  # 用户 ID
    model = Column(String(50), nullable=True, default="qwen2.5:7b")
    input_tokens = Column(Integer, nullable=False)
    output_tokens_limit = Column(Integer, nullable=False)
    max_latency = Column(Integer, nullable=False)
    bid_price = Column(Float, nullable=False)
    callback_url = Column(String(500), nullable=True)
    prompt = Column(Text, nullable=True)
    
    status = Column(SQLEnum(JobStatusDB), default=JobStatusDB.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    matched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Pre-lock 字段
    pre_locked_at = Column(DateTime, nullable=True)
    pre_lock_expires_at = Column(DateTime, nullable=True)
    
    # 执行结果
    actual_output_tokens = Column(Integer, nullable=True)
    final_price = Column(Float, nullable=True)
    result = Column(Text, nullable=True)  # base64 encoded
    
    # 重试
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)
    
    # 关联
    match = relationship("MatchDB", back_populates="job", uselist=False)
    escrow = relationship("EscrowDB", back_populates="job", uselist=False)


class NodeDB(Base):
    """Node 数据库模型"""
    __tablename__ = "nodes"
    
    node_id = Column(String(36), primary_key=True)
    gpu_type = Column(String(50), nullable=False)
    vram_gb = Column(Integer, nullable=False)
    gpu_count = Column(Integer, default=1)
    
    # ===== GPU DETAILS (from system_info.py) =====
    # GPU 详细信息（来自 system_info.py）
    gpu_qty = Column(Integer, default=1)  # GPU 数量
    gpu_vram_gb = Column(Float, default=0.0)  # 每卡显存 GB
    gpu_pooled = Column(Boolean, default=False)  # 是否可池化
    
    # ===== OS INFO (from system_info.py) =====
    # 操作系统信息（来自 system_info.py）
    os_name = Column(String(50), nullable=True)  # 操作系统名称
    os_version = Column(String(50), nullable=True)  # 操作系统版本
    hostname = Column(String(100), nullable=True)  # 主机名
    
    # ===== REQUIRED: runtime and model =====
    runtime = Column(String(20), nullable=False)  # ollama, vllm, tensorrt
    model = Column(String(50), nullable=False)  # qwen2.5:7b, llama3:8b
    
    model_support = Column(Text, nullable=False)  # JSON array
    ask_price = Column(Float, nullable=False)  # USDC per token
    avg_latency = Column(Integer, nullable=False)
    region = Column(String(50), nullable=False)
    
    status = Column(SQLEnum(NodeStatusDB), default=NodeStatusDB.OFFLINE)
    stake_amount = Column(Float, default=0.0)
    stake_required = Column(Float, default=0.0)
    stake_tier = Column(SQLEnum(NodeTierDB), default=NodeTierDB.PERSONAL)
    
    registered_at = Column(DateTime, default=datetime.utcnow)
    
    # 用户绑定（注册时从 NodeCreate.user_id 获取）
    user_id = Column(String(36), nullable=True, index=True)
    
    # Cluster 绑定
    cluster_id = Column(String(50), nullable=True, index=True)
    
    # 关联
    stake_record = relationship("StakeRecordDB", back_populates="node", uselist=False)
    matches = relationship("MatchDB", back_populates="node")


class MatchDB(Base):
    """Match 数据库模型"""
    __tablename__ = "matches"
    
    match_id = Column(String(36), primary_key=True)
    job_id = Column(String(36), ForeignKey("jobs.job_id"), nullable=False)
    node_id = Column(String(36), ForeignKey("nodes.node_id"), nullable=False)
    
    locked_price = Column(Float, nullable=False)
    matched_at = Column(DateTime, default=datetime.utcnow)
    
    # 执行结果
    result_hash = Column(String(100), nullable=True)
    actual_latency_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)  # Node Agent 错误信息
    
    # 验证
    verified = Column(Boolean, default=False)
    verification_layer = Column(Integer, nullable=True)
    layer2_consistency = Column(Float, nullable=True)
    
    # 结算
    settled = Column(Boolean, default=False)
    settled_at = Column(DateTime, nullable=True)
    
    # 重试
    retry_count = Column(Integer, default=0)
    original_match_id = Column(String(36), nullable=True)
    
    # 关联
    job = relationship("JobDB", back_populates="match")
    node = relationship("NodeDB", back_populates="matches")
    escrow = relationship("EscrowDB", back_populates="match", uselist=False)


class EscrowDB(Base):
    """Escrow 数据库模型"""
    __tablename__ = "escrows"
    
    escrow_id = Column(String(36), primary_key=True)
    job_id = Column(String(36), ForeignKey("jobs.job_id"), nullable=False)
    match_id = Column(String(36), ForeignKey("matches.match_id"), nullable=True)
    
    # 金额（USDC）
    locked_amount = Column(Float, nullable=False)
    spent_amount = Column(Float, default=0.0)
    refund_amount = Column(Float, default=0.0)
    
    status = Column(SQLEnum(EscrowStatusDB), default=EscrowStatusDB.LOCKED)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 时间字段
    completed_at = Column(DateTime, nullable=True)  # Job 完成时间
    auto_complete_at = Column(DateTime, nullable=True)  # 计划自动完成时间
    settled_at = Column(DateTime, nullable=True)
    refunded_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    # 取消信息
    cancelled_by = Column(String(50), nullable=True)
    cancel_reason = Column(Text, nullable=True)
    
    # 结算详情
    actual_tokens = Column(Integer, nullable=True)
    actual_cost = Column(Float, nullable=True)
    platform_fee = Column(Float, nullable=True)
    node_earn = Column(Float, nullable=True)
    
    # 退款原因
    refund_reason = Column(Text, nullable=True)
    
    # 关联
    job = relationship("JobDB", back_populates="escrow")
    match = relationship("MatchDB", back_populates="escrow")


class StakeRecordDB(Base):
    """Stake 记录数据库模型"""
    __tablename__ = "stake_records"
    
    id = Column(String(36), primary_key=True)
    node_id = Column(String(36), ForeignKey("nodes.node_id"), nullable=False)
    amount = Column(Float, nullable=False)
    tx_hash = Column(String(100), nullable=False)
    status = Column(String(20), default="active")  # active, frozen, released
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关联
    node = relationship("NodeDB", back_populates="stake_record")


class DisputeDB(Base):
    """争议记录数据库模型"""
    __tablename__ = "disputes"
    
    dispute_id = Column(String(36), primary_key=True)
    node_id = Column(String(36), ForeignKey("nodes.node_id"), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(20), default="pending")  # pending, frozen, under_review, resolved
    created_at = Column(DateTime, default=datetime.utcnow)
    frozen_at = Column(DateTime, nullable=True)
    appeal_deadline = Column(DateTime, nullable=True)
    
    # 关联的 Match IDs（JSON array）
    match_ids = Column(Text, nullable=True)


class AppealDB(Base):
    """申诉数据库模型"""
    __tablename__ = "appeals"
    
    appeal_id = Column(String(36), primary_key=True)
    dispute_id = Column(String(36), ForeignKey("disputes.dispute_id"), nullable=False)
    node_id = Column(String(36), ForeignKey("nodes.node_id"), nullable=False)
    evidence = Column(Text, nullable=False)  # base64 encoded
    message = Column(Text, nullable=False)
    status = Column(String(20), default="submitted")  # submitted, reviewed, rejected, accepted
    submitted_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)


class WalletAccountDB(Base):
    """钱包账户数据库模型 (TD-004)"""
    __tablename__ = "wallet_accounts"
    
    account_id = Column(String(36), primary_key=True)
    address = Column(String(50), nullable=False)
    balance = Column(Float, nullable=False, default=0.0)
    role = Column(String(20), nullable=False)  # buyer, node, system
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==================== User Models / 用户模型 ====================

class UserDB(Base):
    """
    User Database Model
    用户数据库模型
    
    Primary Key: user_id (UUID)
    邮箱作为唯一标识（但不是主键）
    
    Supports multiple auth providers:
    - Google OAuth
    - GitHub OAuth
    - Email + Password
    
    Binds to Node for reputation sync
    """
    __tablename__ = "users"
    
    # Primary key: UUID
    user_id = Column(String(36), primary_key=True)  # UUID as primary key
    
    # Auth info
    auth_provider = Column(String(20), nullable=False)  # google, github, email
    oauth_id = Column(String(100), nullable=True)  # OAuth provider user ID
    oauth_email = Column(String(255), nullable=True)  # OAuth email (for OAuth users)
    password_hash = Column(String(100), nullable=True)  # bcrypt hash
    
    # Unique identifier: email (not primary key, but unique)
    email = Column(String(255), nullable=False, unique=True, index=True)  # Email (unique)
    
    # Profile
    username = Column(String(50), nullable=True, unique=True, index=True)
    avatar_url = Column(String(500), nullable=True)
    
    # Role & Status
    role = Column(String(20), default="user")  # user, node_operator, admin
    status = Column(String(20), default="active")  # active, suspended, deleted
    
    # Node binding (1:N - 用户可以有多个节点)
    # 节点绑定（系统自动维护）
    # 存储为 JSON 字符串: ["node_id_1", "node_id_2"]
    node_ids = Column(Text, nullable=True, default="[]")  # JSON array of node_ids
    bound_at = Column(DateTime, nullable=True)  # 最后绑定时间
    
    # Wallet binding (for settlement)
    # 钱包绑定（用于结算）
    wallet_address = Column(String(100), nullable=True, index=True)
    wallet_type = Column(String(20), nullable=True)  # evm, solana, etc.
    wallet_verified = Column(Boolean, default=False)
    
    # Reputation
    # 声誉评分
    reputation_score = Column(Float, default=0.5)  # 0.0 - 1.0
    total_jobs = Column(Integer, default=0)
    successful_jobs = Column(Integer, default=0)
    failed_jobs = Column(Integer, default=0)
    
    # Stats
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    login_count = Column(Integer, default=0)
    
    # Metadata (JSON)
    user_metadata = Column(Text, nullable=True)  # JSON string
    
    def __repr__(self):
        return f"<UserDB(user_id={self.user_id}, email={self.email})>"


class UserSessionDB(Base):
    """
    User Session Database Model
    用户会话数据库模型
    
    For JWT token management
    """
    __tablename__ = "user_sessions"
    
    session_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=False, index=True)
    token = Column(String(500), nullable=False, unique=True, index=True)
    
    # Session info
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Expiration
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Status
    is_active = Column(Boolean, default=True)


class WalletTransactionDB(Base):
    """钱包交易数据库模型 (TD-004)"""
    __tablename__ = "wallet_transactions"
    
    tx_hash = Column(String(50), primary_key=True)
    account_id = Column(String(36), ForeignKey("wallet_accounts.account_id"), nullable=False)
    counterparty = Column(String(36), nullable=True)
    tx_type = Column(String(30), nullable=False)  # initialize, transfer, escrow_lock, escrow_release, settle, etc.
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    memo = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # 关联
    account = relationship("WalletAccountDB")
