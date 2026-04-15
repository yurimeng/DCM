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

# ==================== Auth Routes / 认证路由 ====================

@router.post("/register")
async def register_user(
    body: dict = Body(...),
    db: Session = Depends(get_db)
):
    """
    Register new user (Email + Password)
    
    Input: {email, password}
    Output: {status: "OK", user_id: "xxx"} or {status: "Failed", error: "..."}
    """
    email = body.get("email")
    password = body.get("password")
    
    if not email or not password:
        return {"status": "Failed", "error": "email and password required"}
    
    if len(password) < 8:
        return {"status": "Failed", "error": "password must be at least 8 characters"}
    
    # Check if email exists
    user_repo = UserRepository(db)
    if user_repo.get_by_email(email):
        return {"status": "Failed", "error": "Email already registered"}
    
    # Create user
    import uuid
    from ..models import User, AuthProvider
    
    user = User(
        user_id=str(uuid.uuid4()),
        username=email.split("@")[0],
        email=email,
        auth_provider=AuthProvider.EMAIL,
    )
    user.password_hash=User.hash_password(password)
    
    db_user = user_repo.create(user)
    
    return {"status": "OK", "user_id": db_user.user_id}


@router.post("/login")
async def login_user(
    body: dict = Body(...),
    db: Session = Depends(get_db)
):
    """
    User Login
    
    Input: {email, password}
    Output: {status: "OK", user_id: "xxx"} or {status: "Failed", error: "..."}
    """
    email = body.get("email")
    password = body.get("password")
    
    if not email or not password:
        return {"status": "Failed", "error": "email and password required"}
    
    user_repo = UserRepository(db)
    db_user = user_repo.get_by_email(email)
    
    if not db_user:
        return {"status": "Failed", "error": "Email not found"}
    
    if not User.verify_password(password, db_user.password_hash):
        return {"status": "Failed", "error": "Invalid password"}
    
    return {"status": "OK", "user_id": db_user.user_id}
