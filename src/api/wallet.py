"""
Wallet API - 模拟钱包管理
用于测试环境
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from ..core.wallet import wallet_service

router = APIRouter(prefix="/api/v1/wallet", tags=["wallet"])


class CreateAccountRequest(BaseModel):
    """创建账户请求"""
    role: str  # "buyer" | "node"
    initial_balance: float = 0.0


class TransferRequest(BaseModel):
    """转账请求"""
    from_account_id: str
    to_account_id: str
    amount: float
    memo: str = ""


class EscrowLockRequest(BaseModel):
    """Escrow 锁定请求"""
    buyer_id: str
    amount: float
    job_id: str


class EscrowReleaseRequest(BaseModel):
    """Escrow 释放请求"""
    buyer_id: str
    amount: float
    job_id: str


class EscrowSettleRequest(BaseModel):
    """Escrow 结算请求"""
    job_id: str
    buyer_id: str
    node_id: str
    node_amount: float
    platform_amount: float


# ===== 初始化 =====

@router.post("/initialize")
async def initialize_wallet():
    """
    初始化测试钱包
    
    创建预设的测试账户：
    - 3 个 Buyer（各 100 USDC）
    - 3 个 Node（各 50 USDC）
    - 1 个 System
    """
    accounts = wallet_service.initialize_test_accounts()
    
    return {
        "initialized": True,
        "accounts": {
            account_id: acc.to_dict()
            for account_id, acc in accounts.items()
        },
    }


# ===== 账户管理 =====

@router.post("/accounts")
async def create_account(request: CreateAccountRequest):
    """创建新账户"""
    if request.role not in ["buyer", "node", "system"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    account = wallet_service.create_account(
        role=request.role,
        initial_balance=request.initial_balance,
    )
    
    return account.to_dict()


@router.get("/accounts")
async def list_accounts(role: Optional[str] = None):
    """列出账户"""
    accounts = wallet_service.get_all_accounts(role)
    
    return {
        "items": [acc.to_dict() for acc in accounts],
        "total": len(accounts),
    }


@router.get("/accounts/{account_id}")
async def get_account(account_id: str):
    """获取账户详情"""
    account = wallet_service.get_account(account_id)
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return account.to_dict()


@router.get("/accounts/{account_id}/balance")
async def get_balance(account_id: str):
    """获取账户余额"""
    balance = wallet_service.get_balance(account_id)
    
    if balance is None:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return {
        "account_id": account_id,
        "balance": balance,
    }


@router.get("/accounts/{account_id}/transactions")
async def get_transactions(account_id: str):
    """获取账户交易历史"""
    account = wallet_service.get_account(account_id)
    
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return {
        "account_id": account_id,
        "transactions": account.txs,
        "total": len(account.txs),
    }


# ===== 转账 =====

@router.post("/transfer")
async def transfer(request: TransferRequest):
    """账户间转账"""
    success = wallet_service.transfer(
        from_id=request.from_account_id,
        to_id=request.to_account_id,
        amount=request.amount,
        memo=request.memo,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Transfer failed (insufficient balance or invalid account)")
    
    return {
        "success": True,
        "from_account": request.from_account_id,
        "to_account": request.to_account_id,
        "amount": request.amount,
    }


# ===== Escrow 操作 =====

@router.post("/escrow/lock")
async def escrow_lock(request: EscrowLockRequest):
    """锁定 Escrow"""
    success = wallet_service.escrow_lock(
        buyer_id=request.buyer_id,
        amount=request.amount,
        job_id=request.job_id,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Escrow lock failed")
    
    return {
        "success": True,
        "buyer_id": request.buyer_id,
        "amount": request.amount,
        "job_id": request.job_id,
    }


@router.post("/escrow/release")
async def escrow_release(request: EscrowReleaseRequest):
    """释放 Escrow（退款）"""
    success = wallet_service.escrow_release(
        buyer_id=request.buyer_id,
        amount=request.amount,
        job_id=request.job_id,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Escrow release failed")
    
    return {
        "success": True,
        "buyer_id": request.buyer_id,
        "amount": request.amount,
        "job_id": request.job_id,
    }


@router.post("/escrow/settle")
async def escrow_settle(request: EscrowSettleRequest):
    """执行 Escrow 结算"""
    success = wallet_service.escrow_settle(
        job_id=request.job_id,
        buyer_id=request.buyer_id,
        node_id=request.node_id,
        node_amount=request.node_amount,
        platform_amount=request.platform_amount,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Escrow settlement failed")
    
    return {
        "success": True,
        "job_id": request.job_id,
        "node_id": request.node_id,
        "node_amount": request.node_amount,
        "platform_amount": request.platform_amount,
    }


# ===== Stake 操作 =====

@router.post("/stake/deposit")
async def stake_deposit(account_id: str, amount: float):
    """Stake 存款"""
    success = wallet_service.stake_deposit(
        node_id=account_id,
        amount=amount,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Stake deposit failed")
    
    return {
        "success": True,
        "account_id": account_id,
        "amount": amount,
    }


# ===== 统计 =====

@router.get("/stats")
async def get_wallet_stats():
    """获取钱包统计"""
    return wallet_service.get_stats()
