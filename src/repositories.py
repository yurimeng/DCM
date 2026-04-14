"""
Repository Layer - Database Access Abstraction
使用 Repository Pattern 解耦业务逻辑和数据库
"""

from typing import Optional, List
from datetime import datetime
import json
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from .models import (
    JobDB, NodeDB, MatchDB, EscrowDB,
    StakeRecordDB, DisputeDB, AppealDB,
    UserDB, UserSessionDB,
    JobStatusDB, NodeStatusDB, EscrowStatusDB
)
from .models.job import Job, JobStatus
from .models.node import Node, NodeStatus, NodeTier
from .models.match import Match
from .models.escrow import Escrow, EscrowStatus


class JobRepository:
    """Job 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, job: Job) -> JobDB:
        """创建 Job"""
        db_job = JobDB(
            job_id=job.job_id,
            model=job.model,
            input_tokens=job.input_tokens,
            output_tokens_limit=job.output_tokens_limit,
            max_latency=job.max_latency,
            bid_price=job.bid_price,
            callback_url=job.callback_url,
            prompt=job.prompt,
            status=JobStatusDB[job.status.name.upper()],
            retry_count=job.retry_count,
            max_retries=job.max_retries,
        )
        self.db.add(db_job)
        self.db.commit()
        self.db.refresh(db_job)
        return db_job
    
    def get(self, job_id: str) -> Optional[JobDB]:
        """获取 Job"""
        return self.db.query(JobDB).filter(JobDB.job_id == job_id).first()
    
    def update(self, job_id: str, **kwargs) -> Optional[JobDB]:
        """更新 Job"""
        from datetime import datetime
        
        job = self.get(job_id)
        if not job:
            return None
        
        for key, value in kwargs.items():
            if hasattr(job, key):
                # 枚举转换
                if key == "status" and isinstance(value, JobStatus):
                    value = JobStatusDB[value.name.upper()]
                    # 自动设置时间戳
                    if value == JobStatusDB.MATCHED and not job.matched_at:
                        job.matched_at = datetime.utcnow()
                    elif value == JobStatusDB.COMPLETED and not job.completed_at:
                        job.completed_at = datetime.utcnow()
                setattr(job, key, value)
        
        self.db.commit()
        self.db.refresh(job)
        return job
    
    def list_pending(self, limit: int = 100) -> List[JobDB]:
        """列出待撮合的 Jobs"""
        return self.db.query(JobDB).filter(
            JobDB.status == JobStatusDB.PENDING
        ).order_by(
            desc(JobDB.bid_price),
            asc(JobDB.created_at)
        ).limit(limit).all()
    
    def list_by_status(self, status: JobStatus, limit: int = 100, offset: int = 0) -> List[JobDB]:
        """按状态列出 Jobs"""
        return self.db.query(JobDB).filter(
            JobDB.status == JobStatusDB[status.name.upper()]
        ).offset(offset).limit(limit).all()
    
    def to_model(self, db_job: JobDB) -> Job:
        """转换为 Pydantic 模型"""
        return Job(
            job_id=db_job.job_id,
            model=db_job.model,
            input_tokens=db_job.input_tokens,
            output_tokens_limit=db_job.output_tokens_limit,
            max_latency=db_job.max_latency,
            bid_price=db_job.bid_price,
            callback_url=db_job.callback_url,
            status=JobStatus[db_job.status.name.lower()],
            created_at=db_job.created_at,
            matched_at=db_job.matched_at,
            completed_at=db_job.completed_at,
            actual_output_tokens=db_job.actual_output_tokens,
            final_price=db_job.final_price,
            result=db_job.result,
            retry_count=db_job.retry_count,
            max_retries=db_job.max_retries,
        )


class NodeRepository:
    """Node 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, node: Node) -> NodeDB:
        """Create Node / 创建 Node"""
        db_node = NodeDB(
            node_id=node.node_id,
            gpu_type=node.gpu_type,
            vram_gb=node.vram_gb,
            gpu_count=node.gpu_count,
            # GPU Details / GPU 详细信息
            gpu_qty=getattr(node, 'gpu_qty', node.gpu_count),
            gpu_vram_gb=getattr(node, 'gpu_vram_gb', node.vram_gb),
            gpu_pooled=getattr(node, 'gpu_pooled', False),
            # OS Info / 操作系统信息
            os_name=getattr(node, 'os_name', ''),
            os_version=getattr(node, 'os_version', ''),
            hostname=getattr(node, 'hostname', ''),
            # Required: runtime and model / 必填：runtime 和 model
            runtime=node.runtime,
            model=node.model,
            model_support=json.dumps(node.model_support),
            ask_price=node.ask_price,
            avg_latency=node.avg_latency,
            region=node.region,
            status=NodeStatusDB[node.status.name.upper()],
            stake_amount=node.stake_amount,
            stake_required=node.stake_required,
            stake_tier=node.stake_tier.value,
        )
        self.db.add(db_node)
        self.db.commit()
        self.db.refresh(db_node)
        return db_node
    
    def get(self, node_id: str) -> Optional[NodeDB]:
        """获取 Node"""
        return self.db.query(NodeDB).filter(NodeDB.node_id == node_id).first()
    
    def update(self, node_id: str, **kwargs) -> Optional[NodeDB]:
        """更新 Node"""
        node = self.get(node_id)
        if not node:
            return None
        
        for key, value in kwargs.items():
            if hasattr(node, key):
                # 枚举转换
                if key == "status" and isinstance(value, NodeStatus):
                    value = NodeStatusDB[value.name.upper()]
                setattr(node, key, value)
        
        self.db.commit()
        self.db.refresh(node)
        return node
    
    def list_online(self) -> List[NodeDB]:
        """列出在线节点"""
        return self.db.query(NodeDB).filter(
            NodeDB.status == NodeStatusDB.ONLINE
        ).order_by(asc(NodeDB.ask_price)).all()
    
    def list_all(self, limit: int = 100, offset: int = 0) -> List[NodeDB]:
        """列出所有节点"""
        return self.db.query(NodeDB).offset(offset).limit(limit).all()
    
    def update_heartbeat(self, node_id: str) -> Optional[NodeDB]:
        """更新心跳时间"""
        node = self.get(node_id)
        if node:
            node.last_heartbeat = datetime.utcnow()
            self.db.commit()
            self.db.refresh(node)
        return node
    
    def to_model(self, db_node: NodeDB) -> Node:
        """转换为 Pydantic 模型"""
        return Node(
            node_id=db_node.node_id,
            gpu_type=db_node.gpu_type,
            vram_gb=db_node.vram_gb,
            model_support=json.loads(db_node.model_support),
            ask_price=db_node.ask_price,
            avg_latency=db_node.avg_latency,
            region=db_node.region,
            status=NodeStatus[db_node.status.name.lower()],
            stake_amount=db_node.stake_amount,
            stake_required=db_node.stake_required,
            stake_tier=NodeTier(db_node.stake_tier),
            registered_at=db_node.registered_at,
            last_heartbeat=db_node.last_heartbeat,
        )


class MatchRepository:
    """Match 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, match: Match) -> MatchDB:
        """创建 Match"""
        db_match = MatchDB(
            match_id=match.match_id,
            job_id=match.job_id,
            node_id=match.node_id,
            locked_price=match.locked_price,
            matched_at=match.matched_at,
            retry_count=match.retry_count,
            original_match_id=match.original_match_id,
        )
        self.db.add(db_match)
        self.db.commit()
        self.db.refresh(db_match)
        return db_match
    
    def get(self, match_id: str) -> Optional[MatchDB]:
        """获取 Match"""
        return self.db.query(MatchDB).filter(MatchDB.match_id == match_id).first()
    
    def get_by_job(self, job_id: str) -> Optional[MatchDB]:
        """根据 Job ID 获取 Match"""
        return self.db.query(MatchDB).filter(MatchDB.job_id == job_id).first()
    
    def update(self, match_id: str, **kwargs) -> Optional[MatchDB]:
        """更新 Match"""
        match = self.get(match_id)
        if not match:
            return None
        
        for key, value in kwargs.items():
            if hasattr(match, key):
                setattr(match, key, value)
        
        self.db.commit()
        self.db.refresh(match)
        return match
    
    def list_recent(self, limit: int = 100) -> List[MatchDB]:
        """列出最近的 Matches"""
        return self.db.query(MatchDB).order_by(
            desc(MatchDB.matched_at)
        ).limit(limit).all()
    
    def to_model(self, db_match: MatchDB) -> Match:
        """转换为 Pydantic 模型"""
        return Match(
            match_id=db_match.match_id,
            job_id=db_match.job_id,
            node_id=db_match.node_id,
            locked_price=db_match.locked_price,
            matched_at=db_match.matched_at,
            result_hash=db_match.result_hash,
            actual_latency_ms=db_match.actual_latency_ms,
            verified=db_match.verified,
            verification_layer=db_match.verification_layer,
            layer2_consistency=db_match.layer2_consistency,
            settled=db_match.settled,
            settled_at=db_match.settled_at,
            retry_count=db_match.retry_count,
            original_match_id=db_match.original_match_id,
        )


class EscrowRepository:
    """Escrow 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, escrow: Escrow) -> EscrowDB:
        """创建 Escrow"""
        db_escrow = EscrowDB(
            escrow_id=escrow.escrow_id,
            job_id=escrow.job_id,
            match_id=escrow.match_id,
            locked_amount=escrow.locked_amount,
            spent_amount=escrow.spent_amount,
            refund_amount=escrow.refund_amount,
            status=EscrowStatusDB[escrow.status.name.upper()],
        )
        self.db.add(db_escrow)
        self.db.commit()
        self.db.refresh(db_escrow)
        return db_escrow
    
    def get(self, escrow_id: str) -> Optional[EscrowDB]:
        """获取 Escrow"""
        return self.db.query(EscrowDB).filter(EscrowDB.escrow_id == escrow_id).first()
    
    def get_by_job(self, job_id: str) -> Optional[EscrowDB]:
        """根据 Job ID 获取 Escrow"""
        return self.db.query(EscrowDB).filter(EscrowDB.job_id == job_id).first()
    
    def get_by_match(self, match_id: str) -> Optional[EscrowDB]:
        """根据 Match ID 获取 Escrow"""
        return self.db.query(EscrowDB).filter(EscrowDB.match_id == match_id).first()
    
    def update(self, escrow_id: str, **kwargs) -> Optional[EscrowDB]:
        """更新 Escrow"""
        escrow = self.get(escrow_id)
        if not escrow:
            return None
        
        for key, value in kwargs.items():
            if hasattr(escrow, key):
                if key == "status" and isinstance(value, EscrowStatus):
                    value = EscrowStatusDB[value.name.upper()]
                setattr(escrow, key, value)
        
        self.db.commit()
        self.db.refresh(escrow)
        return escrow
    
    def to_model(self, db_escrow: EscrowDB) -> Escrow:
        """转换为 Pydantic 模型"""
        return Escrow(
            escrow_id=db_escrow.escrow_id,
            job_id=db_escrow.job_id,
            match_id=db_escrow.match_id,
            locked_amount=db_escrow.locked_amount,
            spent_amount=db_escrow.spent_amount,
            refund_amount=db_escrow.refund_amount,
            status=EscrowStatus[db_escrow.status.name.lower()],
            created_at=db_escrow.created_at,
            settled_at=db_escrow.settled_at,
            refunded_at=db_escrow.refunded_at,
            actual_tokens=db_escrow.actual_tokens,
            actual_cost=db_escrow.actual_cost,
            platform_fee=db_escrow.platform_fee,
            node_earn=db_escrow.node_earn,
            refund_reason=db_escrow.refund_reason,
        )


# ==================== User Repository / 用户仓储 ====================

class UserRepository:
    """
    User Data Access
    用户数据访问
    
    Supports:
    - Create user with multiple auth providers
    - Find user by email, oauth_id, or user_id
    - Bind/unbind node
    - Update reputation
    - Validate user status (disabled check)
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    @staticmethod
    def is_valid_uuid(user_id: str) -> bool:
        """
        Validate UUID format
        验证 UUID 格式
        """
        import re
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )
        return bool(uuid_pattern.match(user_id))
    
    def validate_user_id(self, user_id: str) -> tuple[bool, Optional[UserDB], str]:
        """
        Validate user ID and check status
        验证用户 ID 并检查状态
        
        Returns:
            (is_valid, user_db, error_message)
        """
        # Check UUID format
        if not self.is_valid_uuid(user_id):
            return False, None, "Invalid user ID format"
        
        # Check if user exists
        user = self.get(user_id)
        if not user:
            return False, None, "User not found"
        
        # Check if user is disabled
        if user.status == "disabled":
            return False, None, "User is disabled"
        
        # Check if user is deleted
        if user.status == "deleted":
            return False, None, "User account deleted"
        
        # Check if user is suspended
        if user.status == "suspended":
            return False, None, "User account suspended"
        
        return True, user, ""
    
    def create(self, user) -> UserDB:
        """
        Create new user
        创建新用户
        """
        db_user = UserDB(
            user_id=user.user_id,
            auth_provider=user.auth_provider.value,
            oauth_id=user.oauth_id,
            oauth_email=user.oauth_email,
            email=user.email,
            password_hash=user.password_hash,
            username=user.username,
            avatar_url=user.avatar_url,
            role=user.role.value,
            status=user.status.value,
            node_ids=json.dumps(user.node_ids) if user.node_ids else "[]",
            bound_at=user.bound_at,
            wallet_address=user.wallet_address,
            wallet_type=user.wallet_type,
            wallet_verified=user.wallet_verified,
            reputation_score=user.reputation_score,
            total_jobs=user.total_jobs,
            successful_jobs=user.successful_jobs,
            failed_jobs=user.failed_jobs,
            created_at=user.created_at,
            last_login=user.last_login,
            login_count=user.login_count,
            user_metadata=json.dumps(user.metadata) if user.metadata else None,
        )
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        return db_user
    
    def get(self, user_id: str) -> Optional[UserDB]:
        """
        Get user by ID
        根据 ID 获取用户
        """
        return self.db.query(UserDB).filter(UserDB.user_id == user_id).first()
    
    def get_by_email(self, email: str) -> Optional[UserDB]:
        """
        Get user by email
        根据邮箱获取用户
        """
        return self.db.query(UserDB).filter(UserDB.email == email.lower()).first()
    
    def get_by_oauth(self, provider: str, oauth_id: str) -> Optional[UserDB]:
        """
        Get user by OAuth provider and ID
        根据 OAuth 提供商和 ID 获取用户
        """
        return self.db.query(UserDB).filter(
            UserDB.auth_provider == provider,
            UserDB.oauth_id == oauth_id
        ).first()
    
    def get_by_username(self, username: str) -> Optional[UserDB]:
        """
        Get user by username
        根据用户名获取用户
        """
        return self.db.query(UserDB).filter(UserDB.username == username).first()
    
    def get_by_node(self, node_id: str) -> Optional[UserDB]:
        """
        Get user bound to node
        获取绑定到节点的用户
        """
        return self.db.query(UserDB).filter(UserDB.node_id == node_id).first()
    
    def get_by_wallet(self, wallet_address: str) -> Optional[UserDB]:
        """
        Get user by wallet address
        根据钱包地址获取用户
        """
        return self.db.query(UserDB).filter(UserDB.wallet_address == wallet_address).first()
    
    def bind_wallet(
        self,
        user_id: str,
        wallet_address: str,
        wallet_type: str = "evm"
    ) -> Optional[UserDB]:
        """
        Bind wallet to user
        绑定钱包到用户
        """
        user = self.get(user_id)
        if not user:
            return None
        
        # Check if wallet is already bound to another user
        existing = self.get_by_wallet(wallet_address)
        if existing and existing.user_id != user_id:
            return None
        
        user.wallet_address = wallet_address
        user.wallet_type = wallet_type
        user.wallet_verified = False
        
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def verify_wallet(self, user_id: str) -> Optional[UserDB]:
        """
        Verify wallet for user
        验证用户钱包
        """
        user = self.get(user_id)
        if not user or not user.wallet_address:
            return None
        
        user.wallet_verified = True
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def unbind_wallet(self, user_id: str) -> Optional[UserDB]:
        """
        Unbind wallet from user
        解绑钱包
        """
        user = self.get(user_id)
        if not user:
            return None
        
        user.wallet_address = None
        user.wallet_type = None
        user.wallet_verified = False
        
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def add_node_to_user(self, user_id: str, node_id: str) -> Optional[UserDB]:
        """
        Add node to user's node_ids list
        添加节点到用户的 node_ids 列表（系统自动维护）
        """
        user = self.get(user_id)
        if not user:
            return None
        
        # Parse existing node_ids
        node_ids = json.loads(user.node_ids or "[]")
        
        # Add if not exists
        if node_id not in node_ids:
            node_ids.append(node_id)
            user.node_ids = json.dumps(node_ids)
            user.bound_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(user)
        
        return user
    
    def remove_node_from_user(self, user_id: str, node_id: str) -> Optional[UserDB]:
        """
        Remove node from user's node_ids list
        从用户的 node_ids 列表移除节点（系统自动维护）
        """
        user = self.get(user_id)
        if not user:
            return None
        
        # Parse existing node_ids
        node_ids = json.loads(user.node_ids or "[]")
        
        # Remove if exists
        if node_id in node_ids:
            node_ids.remove(node_id)
            user.node_ids = json.dumps(node_ids)
            self.db.commit()
            self.db.refresh(user)
        
        return user
    
    def get_by_node(self, node_id: str) -> Optional[UserDB]:
        """
        Get user bound to node (search in node_ids list)
        获取绑定到节点的用户
        """
        users = self.db.query(UserDB).all()
        for user in users:
            node_ids = json.loads(user.node_ids or "[]")
            if node_id in node_ids:
                return user
        return None
    
    def update(self, user_id: str, **kwargs) -> Optional[UserDB]:
        """
        Update user
        更新用户
        """
        user = self.get(user_id)
        if not user:
            return None
        
        for key, value in kwargs.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)
        
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def update_reputation(
        self,
        user_id: str,
        success: bool
    ) -> Optional[UserDB]:
        """
        Update user reputation based on job result
        根据 Job 结果更新用户声誉
        """
        user = self.get(user_id)
        if not user:
            return None
        
        # Update job stats
        user.total_jobs += 1
        if success:
            user.successful_jobs += 1
            # Success bonus
            bonus = 0.01 * (1 - user.reputation_score)
            user.reputation_score = min(1.0, user.reputation_score + bonus)
        else:
            user.failed_jobs += 1
            # Failure penalty
            user.reputation_score = max(0.0, user.reputation_score - 0.02)
        
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def bind_node(self, user_id: str, node_id: str) -> Optional[UserDB]:
        """
        Bind user to node
        绑定用户到节点
        """
        user = self.get(user_id)
        if not user:
            return None
        
        if user.node_id and user.node_id != node_id:
            # Already bound to another node
            return None
        
        user.node_id = node_id
        user.bound_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def unbind_node(self, user_id: str) -> Optional[UserDB]:
        """
        Unbind user from node
        解绑节点
        """
        user = self.get(user_id)
        if not user:
            return None
        
        user.node_id = None
        user.bound_at = None
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def update_login(self, user_id: str) -> Optional[UserDB]:
        """
        Update login stats
        更新登录统计
        """
        user = self.get(user_id)
        if not user:
            return None
        
        user.last_login = datetime.utcnow()
        user.login_count += 1
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def list_users(
        self,
        skip: int = 0,
        limit: int = 100,
        status: str = None
    ) -> List[UserDB]:
        """
        List users with pagination
        分页列出用户
        """
        query = self.db.query(UserDB)
        
        if status:
            query = query.filter(UserDB.status == status)
        
        return query.order_by(desc(UserDB.created_at)).offset(skip).limit(limit).all()
    
    def delete(self, user_id: str) -> bool:
        """
        Soft delete user
        软删除用户
        """
        user = self.get(user_id)
        if not user:
            return False
        
        user.status = "deleted"
        self.db.commit()
        return True
    
    def to_model(self, db_user: UserDB) -> 'User':
        """
        Convert DB model to Pydantic model
        转换数据库模型为 Pydantic 模型
        """
        from .models.user import (
            User, UserStatus as UserStatusEnum,
            UserRole as UserRoleEnum, AuthProvider as AuthProviderEnum
        )
        
        return User(
            user_id=db_user.user_id,
            auth_provider=AuthProviderEnum(db_user.auth_provider),
            oauth_id=db_user.oauth_id,
            oauth_email=db_user.oauth_email,
            email=db_user.email,
            password_hash=db_user.password_hash,
            username=db_user.username,
            avatar_url=db_user.avatar_url,
            role=UserRoleEnum(db_user.role),
            status=UserStatusEnum(db_user.status),
            node_ids=json.loads(db_user.node_ids) if db_user.node_ids else [],
            bound_at=db_user.bound_at,
            wallet_address=db_user.wallet_address,
            wallet_type=db_user.wallet_type,
            wallet_verified=db_user.wallet_verified,
            reputation_score=db_user.reputation_score,
            total_jobs=db_user.total_jobs,
            successful_jobs=db_user.successful_jobs,
            failed_jobs=db_user.failed_jobs,
            created_at=db_user.created_at,
            last_login=db_user.last_login,
            login_count=db_user.login_count,
            metadata=json.loads(db_user.user_metadata) if db_user.user_metadata else {},
        )
