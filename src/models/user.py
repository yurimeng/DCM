"""
User Model - DCM v3.1
用户模型 - 支持多种认证方式和 Reputation 绑定

Features:
- Multiple auth providers: Google, GitHub, Email
- Password hashing (bcrypt)
- Node binding (optional)
- Reputation score from node
"""

from enum import Enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
import hashlib
import secrets


class AuthProvider(str, Enum):
    """
    Authentication Provider
    认证提供商
    """
    GOOGLE = "google"
    GITHUB = "github"
    EMAIL = "email"


class UserRole(str, Enum):
    """
    User Role
    用户角色
    """
    USER = "user"
    NODE_OPERATOR = "node_operator"
    ADMIN = "admin"


class UserStatus(str, Enum):
    """
    User Status
    用户状态
    """
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"
    DELETED = "deleted"
    
    @classmethod
    def is_valid(cls, status: str) -> bool:
        """Check if status is valid for login"""
        return status in [cls.ACTIVE.value]
    
    def can_login(self) -> bool:
        """Check if user with this status can login"""
        return self == UserStatus.ACTIVE


class UserCreate(BaseModel):
    """
    User Creation Request
    用户创建请求
    """
    # Auth provider
    # 认证方式
    auth_provider: AuthProvider = Field(..., description="Auth provider: google, github, email")
    
    # OAuth fields (for Google/GitHub)
    # OAuth 字段
    oauth_id: Optional[str] = Field(None, description="OAuth provider user ID")
    oauth_email: Optional[str] = Field(None, description="OAuth email")
    
    # Email fields (for email auth)
    # 邮箱字段
    email: Optional[str] = Field(None, description="Email address")
    
    # Password (only for email auth, will be hashed)
    # 密码（仅用于邮箱认证，将被哈希）
    password: Optional[str] = Field(None, description="Password (will be hashed)")
    
    # Username (optional)
    # 用户名（可选）
    username: Optional[str] = Field(None, description="Username")
    
    # Node binding (optional)
    # 节点绑定（可选）
    node_id: Optional[str] = Field(None, description="Bound node ID (optional)")
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v and '@' not in v:
            raise ValueError("Invalid email format")
        return v.lower() if v else None
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if v and len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class User(BaseModel):
    """
    User Model (Complete)
    用户模型（完整）
    
    Attributes:
        user_id: Unique user identifier
        auth_provider: Authentication provider (google, github, email)
        email: Email address
        username: Username (optional)
        role: User role
        status: User status
        node_id: Bound node ID (optional)
        reputation_score: Reputation score (0-1, derived from node)
        created_at: Creation timestamp
        last_login: Last login timestamp
    """
    user_id: str = Field(..., description="Unique user ID")
    
    # Auth info
    auth_provider: AuthProvider
    oauth_id: Optional[str] = None
    oauth_email: Optional[str] = None  # OAuth provider email
    email: str  # Email is required, unique
    password_hash: Optional[str] = None  # bcrypt hash
    
    # Profile
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    
    # Role & Status
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    
    # Node binding (1:N - 用户可以有多个节点)
    # 节点绑定（系统自动维护，用户不能修改 node_ids）
    node_ids: List[str] = Field(default_factory=list, description="Bound node IDs (system managed)")
    bound_at: Optional[datetime] = None  # 最后绑定时间
    
    # Wallet binding (for settlement)
    # 钱包绑定（用于结算）
    wallet_address: Optional[str] = Field(None, description="Blockchain wallet address (USDC)")
    wallet_type: Optional[str] = Field(None, description="Wallet type: evm, solana, etc.")
    wallet_verified: bool = Field(default=False, description="Wallet verification status")
    
    # Reputation
    # 声誉评分
    reputation_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Reputation score (0-1)")
    total_jobs: int = Field(default=0, description="Total jobs completed")
    successful_jobs: int = Field(default=0, description="Successful jobs")
    failed_jobs: int = Field(default=0, description="Failed jobs")
    
    # Stats
    # 统计
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    login_count: int = Field(default=0, description="Login count")
    
    # Metadata
    metadata: dict = Field(default_factory=dict)
    
    @property
    def is_active(self) -> bool:
        """Check if user is active"""
        return self.status == UserStatus.ACTIVE
    
    @property
    def is_node_operator(self) -> bool:
        """Check if user is a node operator"""
        return self.role in [UserRole.NODE_OPERATOR, UserRole.ADMIN]
    
    @property
    def has_nodes(self) -> bool:
        """Check if user has bound any nodes"""
        return len(self.node_ids) > 0 if self.node_ids else False
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        if self.total_jobs == 0:
            return 0.5
        return self.successful_jobs / self.total_jobs
    
    def update_reputation(self, success: bool):
        """
        Update reputation score based on job result
        根据 Job 结果更新声誉评分
        
        Formula:
        - Success: reputation += 0.01 * success_rate_bonus
        - Failure: reputation -= 0.02
        """
        if success:
            # Success bonus based on current success rate
            bonus = 0.01 * (1 - self.reputation_score)
            self.reputation_score = min(1.0, self.reputation_score + bonus)
            self.successful_jobs += 1
        else:
            # Failure penalty
            self.reputation_score = max(0.0, self.reputation_score - 0.02)
            self.failed_jobs += 1
        
        self.total_jobs += 1
    
    def bind_node(self, node_id: str) -> bool:
        """
        Bind user to a node (add to node_ids list)
        绑定用户到节点（添加到 node_ids 列表）
        
        Returns True if successful
        """
        if not self.node_ids:
            self.node_ids = []
        
        if node_id not in self.node_ids:
            self.node_ids.append(node_id)
            self.bound_at = datetime.utcnow()
            return True
        
        return False  # Already bound to this node
    
    def unbind_node(self, node_id: str = None) -> bool:
        """
        Unbind user from node (remove from node_ids list)
        解绑节点（从 node_ids 列表移除）
        
        Args:
            node_id: Specific node to unbind, or None to unbind all
        
        Returns True if successful
        """
        if not self.node_ids:
            return False
        
        if node_id:
            # Unbind specific node
            if node_id in self.node_ids:
                self.node_ids.remove(node_id)
                if len(self.node_ids) == 0:
                    self.bound_at = None
                return True
            return False
        else:
            # Unbind all nodes
            self.node_ids = []
            self.bound_at = None
            return True
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash password using SHA-256 with salt
        使用 SHA-256 加盐哈希密码
        
        Note: In production, use bcrypt or argon2
        """
        salt = secrets.token_hex(16)
        hash_value = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"{salt}${hash_value}"
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify password against hash
        验证密码
        
        Args:
            password: Plain text password
            password_hash: Salt$hash format
        """
        try:
            salt, stored_hash = password_hash.split('$')
            computed_hash = hashlib.sha256((salt + password).encode()).hexdigest()
            return secrets.compare_digest(computed_hash, stored_hash)
        except ValueError:
            return False


class UserResponse(BaseModel):
    """
    User API Response (Public)
    用户 API 响应（公开）
    
    Excludes sensitive fields like password_hash
    """
    user_id: str
    auth_provider: AuthProvider
    email: Optional[str] = None
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    role: UserRole
    status: UserStatus
    node_ids: List[str] = Field(default_factory=list)  # 绑定的节点列表
    has_nodes: bool  # 是否有节点
    # Wallet binding
    # 钱包绑定
    wallet_address: Optional[str] = None
    wallet_type: Optional[str] = None
    wallet_verified: bool = False
    # Reputation
    reputation_score: float
    total_jobs: int
    successful_jobs: int
    failed_jobs: int
    success_rate: float
    created_at: datetime
    last_login: Optional[datetime] = None


class UserLogin(BaseModel):
    """
    User Login Request
    用户登录请求
    """
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")


class AuthResponse(BaseModel):
    """
    Authentication Response
    认证响应
    """
    success: bool
    user: Optional[UserResponse] = None
    access_token: Optional[str] = None
    token_type: str = "bearer"
    message: Optional[str] = None


class NodeReputationBinding(BaseModel):
    """
    Node Reputation Binding
    节点声誉绑定
    
    Binds user reputation to node reputation
    将用户声誉绑定到节点声誉
    """
    user_id: str
    node_id: str
    bound_at: datetime
    sync_enabled: bool = True
    
    def get_node_reputation(self, user: User) -> float:
        """
        Get reputation from node
        从节点获取声誉
        
        If user has bound node, use node's reputation
        如果用户绑定了节点，使用节点的声誉
        """
        return user.reputation_score
