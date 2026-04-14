"""
User API - Authentication & User Management
用户 API - 认证与用户管理

Supports:
- Google OAuth
- GitHub OAuth
- Email + Password
- Node binding
- Wallet binding
- Reputation sync
"""

import uuid
import secrets
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..repositories import UserRepository
from ..models.user import (
    User, UserCreate, UserResponse, UserLogin, AuthResponse,
    AuthProvider, UserRole, UserStatus
)
from ..models.user import UserResponse as UserResponseModel
from ..models.node import NodeStatus

router = APIRouter(prefix="/api/v1/users", tags=["users"])
security = HTTPBearer(auto_error=False)


# ==================== Auth Helpers / 认证辅助 ====================

def user_to_response(user: User) -> dict:
    """
    Convert User model to API response dict
    转换 User 模型为 API 响应字典
    """
    return {
        "user_id": user.user_id,
        "auth_provider": user.auth_provider.value,
        "email": user.email,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "role": user.role.value,
        "status": user.status.value,
        "node_ids": user.node_ids,
        "has_nodes": len(user.node_ids) > 0 if user.node_ids else False,
        "wallet_address": user.wallet_address,
        "wallet_type": user.wallet_type,
        "wallet_verified": user.wallet_verified,
        "reputation_score": user.reputation_score,
        "total_jobs": user.total_jobs,
        "successful_jobs": user.successful_jobs,
        "failed_jobs": user.failed_jobs,
        "success_rate": user.success_rate,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def create_access_token(user_id: str, expires_hours: int = 24) -> str:
    """
    Create access token
    创建访问令牌
    """
    payload = {
        "user_id": user_id,
        "exp": (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat(),  # Convert to ISO string
        "nonce": secrets.token_hex(8)
    }
    # In production, use proper JWT signing
    import base64
    import json
    token_bytes = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(token_bytes).decode()


def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode token
    验证并解码令牌
    """
    try:
        import base64
        import json
        decoded = base64.urlsafe_b64decode(token.encode())
        payload = json.loads(decoded)
        
        # Check expiration
        exp = datetime.fromisoformat(payload["exp"])
        if datetime.utcnow() > exp:
            return None
        
        return payload
    except Exception:
        return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current authenticated user
    获取当前认证用户
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    user_repo = UserRepository(db)
    db_user = user_repo.get(payload["user_id"])
    
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user_repo.to_model(db_user)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Get current user if authenticated (optional)
    获取当前用户（可选）
    """
    if not credentials:
        return None
    
    try:
        payload = verify_token(credentials.credentials)
        if not payload:
            return None
        
        user_repo = UserRepository(db)
        db_user = user_repo.get(payload["user_id"])
        
        if not db_user:
            return None
        
        return user_repo.to_model(db_user)
    except Exception:
        return None


# ==================== Auth Routes / 认证路由 ====================

@router.post("/register", response_model=AuthResponse)
async def register(
    user_create: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Register new user
    注册新用户
    
    Supports:
    - Google OAuth: auth_provider=google, oauth_id, oauth_email
    - GitHub OAuth: auth_provider=github, oauth_id, oauth_email
    - Email: auth_provider=email, email, password
    """
    user_repo = UserRepository(db)
    
    # Check existing user
    if user_create.email:
        existing = user_repo.get_by_email(user_create.email)
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
    
    if user_create.oauth_id and user_create.oauth_email:
        existing = user_repo.get_by_oauth(
            user_create.auth_provider.value,
            user_create.oauth_id
        )
        if existing:
            raise HTTPException(status_code=400, detail="OAuth user already registered")
    
    # Create user
    user = User(
        user_id=str(uuid.uuid4()),
        auth_provider=user_create.auth_provider,
        oauth_id=user_create.oauth_id,
        oauth_email=user_create.oauth_email,
        email=user_create.email,
        password_hash=User.hash_password(user_create.password) if user_create.password else None,
        username=user_create.username,
        node_id=user_create.node_id,
        reputation_score=0.5,  # Default
    )
    
    # Save to database
    db_user = user_repo.create(user)
    
    # Create access token
    access_token = create_access_token(user.user_id)
    
    return AuthResponse(
        success=True,
        user=user_to_response(user),
        access_token=access_token,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    login_data: UserLogin,
    db: Session = Depends(get_db)
):
    """
    Login with email and password
    邮箱密码登录
    """
    user_repo = UserRepository(db)
    
    # Find user by email
    db_user = user_repo.get_by_email(login_data.email)
    
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Verify password
    user = user_repo.to_model(db_user)
    
    if not user.password_hash:
        raise HTTPException(status_code=401, detail="Password not set for this account")
    
    if not User.verify_password(login_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Update login stats
    user_repo.update_login(user.user_id)
    
    # Create access token
    access_token = create_access_token(user.user_id)
    
    # Build user response
    user_resp = UserResponseModel(
        user_id=user.user_id,
        auth_provider=user.auth_provider,
        email=user.email,
        username=user.username,
        avatar_url=user.avatar_url,
        role=user.role,
        status=user.status,
        node_ids=user.node_ids,
        has_nodes=len(user.node_ids) > 0 if user.node_ids else False,
        wallet_address=user.wallet_address,
        wallet_type=user.wallet_type,
        wallet_verified=user.wallet_verified,
        reputation_score=user.reputation_score,
        total_jobs=user.total_jobs,
        successful_jobs=user.successful_jobs,
        failed_jobs=user.failed_jobs,
        success_rate=user.success_rate,
        created_at=user.created_at,
        last_login=user.last_login,
    )
    
    return AuthResponse(
        success=True,
        user=user_resp,
        access_token=access_token,
    )


@router.post("/oauth/google", response_model=AuthResponse)
async def oauth_google(
    oauth_id: str,
    email: str,
    name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    OAuth Google callback
    Google OAuth 回调
    """
    user_repo = UserRepository(db)
    
    # Check if user exists
    db_user = user_repo.get_by_oauth("google", oauth_id)
    
    if not db_user:
        # Create new user
        user = User(
            user_id=str(uuid.uuid4()),
            auth_provider=AuthProvider.GOOGLE,
            oauth_id=oauth_id,
            oauth_email=email,
            email=email,
            username=name,
            avatar_url=avatar_url,
            reputation_score=0.5,
        )
        db_user = user_repo.create(user)
    
    # Update login stats
    user_repo.update_login(db_user.user_id)
    
    # Create access token
    access_token = create_access_token(db_user.user_id)
    
    return AuthResponse(
        success=True,
        user=user_to_response(user),
        access_token=access_token,
    )


@router.post("/oauth/github", response_model=AuthResponse)
async def oauth_github(
    oauth_id: str,
    email: str,
    name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    OAuth GitHub callback
    GitHub OAuth 回调
    """
    user_repo = UserRepository(db)
    
    # Check if user exists
    db_user = user_repo.get_by_oauth("github", oauth_id)
    
    if not db_user:
        # Create new user
        user = User(
            user_id=str(uuid.uuid4()),
            auth_provider=AuthProvider.GITHUB,
            oauth_id=oauth_id,
            oauth_email=email,
            email=email,
            username=name,
            avatar_url=avatar_url,
            reputation_score=0.5,
        )
        db_user = user_repo.create(user)
    
    # Update login stats
    user_repo.update_login(db_user.user_id)
    
    # Create access token
    access_token = create_access_token(db_user.user_id)
    
    return AuthResponse(
        success=True,
        user=user_to_response(user),
        access_token=access_token,
    )


# ==================== User Routes / 用户路由 ====================

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Get current user profile
    获取当前用户资料
    """
    return user_to_response(current_user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, db: Session = Depends(get_db)):
    """
    Get user by ID
    获取用户
    """
    user_repo = UserRepository(db)
    db_user = user_repo.get(user_id)
    
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user_to_response(user_repo.to_model(db_user))


@router.post("/node/bind", response_model=UserResponse)
async def bind_node(
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Bind user to node
    绑定用户到节点
    
    When user binds a node:
    - User's reputation syncs with node's reputation
    - User can manage the node
    """
    user_repo = UserRepository(db)
    
    # Bind node
    db_user = user_repo.bind_node(current_user.user_id, node_id)
    
    if not db_user:
        raise HTTPException(status_code=400, detail="Failed to bind node")
    
    return user_to_response(user_repo.to_model(db_user))


@router.post("/node/unbind", response_model=UserResponse)
async def unbind_node(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Unbind user from node
    解绑节点
    """
    user_repo = UserRepository(db)
    
    # Unbind node
    db_user = user_repo.unbind_node(current_user.user_id)
    
    if not db_user:
        raise HTTPException(status_code=400, detail="Failed to unbind node")
    
    return user_to_response(user_repo.to_model(db_user))


class WalletBindRequest(BaseModel):
    """Wallet bind request / 钱包绑定请求"""
    wallet_address: str
    wallet_type: str = "evm"


@router.post("/wallet/bind", response_model=UserResponse)
async def bind_wallet(
    request: WalletBindRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Bind wallet to user
    绑定钱包到用户
    
    Wallet is used for:
    - Job payment (USDC)
    - Node earnings settlement
    """
    user_repo = UserRepository(db)
    
    # Bind wallet
    db_user = user_repo.bind_wallet(
        current_user.user_id,
        request.wallet_address,
        request.wallet_type
    )
    
    if not db_user:
        raise HTTPException(status_code=400, detail="Failed to bind wallet (already bound to another user)")
    
    return user_to_response(user_repo.to_model(db_user))


@router.post("/wallet/unbind", response_model=UserResponse)
async def unbind_wallet(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Unbind wallet from user
    解绑钱包
    """
    user_repo = UserRepository(db)
    
    # Unbind wallet
    db_user = user_repo.unbind_wallet(current_user.user_id)
    
    if not db_user:
        raise HTTPException(status_code=400, detail="Failed to unbind wallet")
    
    return user_to_response(user_repo.to_model(db_user))


@router.get("/reputation/score")
async def get_reputation_score(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get user reputation score
    获取用户声誉评分
    
    If user has bound node, returns node's reputation
    如果用户绑定了节点，返回节点声誉
    """
    user_repo = UserRepository(db)
    
    # Get user with node info
    db_user = user_repo.get(current_user.user_id)
    
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = user_repo.to_model(db_user)
    
    # If user has bound nodes, get node's reputation
    node_reputation = None
    if user.node_ids and len(user.node_ids) > 0:
        # Import here to avoid circular dependency
        from ..repositories import NodeRepository
        node_repo = NodeRepository(db)
        # Get first node's reputation
        db_node = node_repo.get(user.node_ids[0])
        
        if db_node:
            # Get node's success rate as reputation
            node_reputation = db_node.avg_success_rate if hasattr(db_node, 'avg_success_rate') else 0.5
    
    return {
        "user_id": user.user_id,
        "user_reputation": user.reputation_score,
        "node_ids": user.node_ids,
        "node_reputation": node_reputation,
        "has_nodes": user.has_nodes,
        "has_wallet": user.wallet_address is not None,
        "wallet_verified": user.wallet_verified,
    }


@router.get("/reputation/history")
async def get_reputation_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get user reputation history
    获取用户声誉历史
    """
    user_repo = UserRepository(db)
    db_user = user_repo.get(current_user.user_id)
    
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = user_repo.to_model(db_user)
    
    return {
        "user_id": user.user_id,
        "reputation_score": user.reputation_score,
        "total_jobs": user.total_jobs,
        "successful_jobs": user.successful_jobs,
        "failed_jobs": user.failed_jobs,
        "success_rate": user.success_rate,
        "created_at": user.created_at,
    }
