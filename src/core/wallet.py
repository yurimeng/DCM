"""
Mock Wallet System - 本地测试用账户管理
用于测试环境，模拟链上账户余额
"""

import uuid
import hashlib
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import json


@dataclass
class Account:
    """模拟账户"""
    account_id: str
    address: str  # 类似钱包地址
    balance: float  # USDC 余额
    role: str  # "buyer" | "node" | "system"
    created_at: datetime = field(default_factory=datetime.utcnow)
    txs: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "address": self.address,
            "balance": self.balance,
            "role": self.role,
            "created_at": self.created_at.isoformat(),
            "tx_count": len(self.txs),
        }


class MockWalletService:
    """
    模拟钱包服务
    
    用于测试环境，模拟链上账户和余额操作
    正式环境应替换为真实的链上交互
    
    TD-004: 添加数据库持久化
    """
    
    def __init__(self, db_session=None):
        self._accounts: Dict[str, Account] = {}
        self._initialized = False
        self._db_session = db_session  # 数据库会话
    
    def initialize_test_accounts(self) -> Dict[str, Account]:
        """
        初始化测试账户
        
        创建预设的测试账户：
        - 3 个 Buyer 账户（各有 100 USDC）
        - 3 个 Node 账户（各有 50 USDC stake）
        - 1 个 System 账户（手续费收取）
        
        TD-004: 从数据库加载或创建账户
        """
        if self._initialized:
            return self._accounts
        
        # 尝试从数据库加载账户
        if self._db_session:
            try:
                from ..models.db_models import WalletAccountDB
                db_accounts = self._db_session.query(WalletAccountDB).all()
                if db_accounts:
                    for db_acc in db_accounts:
                        self._accounts[db_acc.account_id] = Account(
                            account_id=db_acc.account_id,
                            address=db_acc.address,
                            balance=db_acc.balance,
                            role=db_acc.role,
                            created_at=db_acc.created_at,
                        )
                    self._initialized = True
                    return self._accounts
            except Exception:
                pass  # 数据库可能不存在，继续创建
        
        # Buyer 账户
        buyers = [
            ("buyer-001", "0xBUYER0000000000000000000000001", 100.0),
            ("buyer-002", "0xBUYER0000000000000000000000002", 100.0),
            ("buyer-003", "0xBUYER0000000000000000000000003", 100.0),
        ]
        
        for account_id, address, balance in buyers:
            self._accounts[account_id] = Account(
                account_id=account_id,
                address=address,
                balance=balance,
                role="buyer",
            )
        
        # Node 账户
        nodes = [
            ("node-001", "0xNODE00000000000000000000000001", 50.0),
            ("node-002", "0xNODE00000000000000000000000002", 50.0),
            ("node-003", "0xNODE00000000000000000000000003", 50.0),
        ]
        
        for account_id, address, balance in nodes:
            self._accounts[account_id] = Account(
                account_id=account_id,
                address=address,
                balance=balance,
                role="node",
            )
        
        # System 账户
        self._accounts["system"] = Account(
            account_id="system",
            address="0xSYSTEM00000000000000000000000001",
            balance=0.0,
            role="system",
        )
        
        self._initialized = True
        
        # 保存到数据库 (TD-004)
        self._save_accounts_to_db()
        
        # 记录初始化交易
        for account in self._accounts.values():
            self._add_tx(
                account.account_id,
                "initialize",
                None,
                account.balance,
                "Initial balance"
            )
        
        return self._accounts
    
    def _save_accounts_to_db(self) -> None:
        """保存所有账户到数据库 (TD-004)"""
        if not self._db_session:
            return
        
        try:
            from ..models.db_models import WalletAccountDB
            for account in self._accounts.values():
                db_acc = self._db_session.query(WalletAccountDB).filter(
                    WalletAccountDB.account_id == account.account_id
                ).first()
                
                if db_acc:
                    db_acc.balance = account.balance
                    db_acc.updated_at = datetime.utcnow()
                else:
                    db_acc = WalletAccountDB(
                        account_id=account.account_id,
                        address=account.address,
                        balance=account.balance,
                        role=account.role,
                    )
                    self._db_session.add(db_acc)
            
            self._db_session.commit()
        except Exception as e:
            self._db_session.rollback()
    
    def _save_balance_to_db(self, account_id: str) -> None:
        """保存单个账户余额到数据库 (TD-004)"""
        if not self._db_session:
            return
        
        try:
            from ..models.db_models import WalletAccountDB
            db_acc = self._db_session.query(WalletAccountDB).filter(
                WalletAccountDB.account_id == account_id
            ).first()
            
            if db_acc and account_id in self._accounts:
                db_acc.balance = self._accounts[account_id].balance
                db_acc.updated_at = datetime.utcnow()
                self._db_session.commit()
        except Exception:
            self._db_session.rollback()
    
    def create_account(self, role: str, initial_balance: float = 0.0) -> Account:
        """
        创建新账户
        
        Args:
            role: "buyer" | "node" | "system"
            initial_balance: 初始余额
        
        Returns:
            新创建的 Account
        """
        account_id = str(uuid.uuid4())
        address = self._generate_address(account_id)
        
        account = Account(
            account_id=account_id,
            address=address,
            balance=initial_balance,
            role=role,
        )
        
        self._accounts[account_id] = account
        
        if initial_balance > 0:
            self._add_tx(account_id, "initialize", None, initial_balance, "Initial balance")
        
        return account
    
    def get_account(self, account_id: str) -> Optional[Account]:
        """获取账户"""
        return self._accounts.get(account_id)
    
    def get_account_by_address(self, address: str) -> Optional[Account]:
        """通过地址获取账户"""
        for account in self._accounts.values():
            if account.address.lower() == address.lower():
                return account
        return None
    
    def get_balance(self, account_id: str) -> float:
        """获取余额"""
        account = self._accounts.get(account_id)
        return account.balance if account else 0.0
    
    def transfer(
        self,
        from_id: str,
        to_id: str,
        amount: float,
        memo: str = ""
    ) -> bool:
        """
        转账
        
        Args:
            from_id: 转出账户 ID
            to_id: 转入账户 ID
            amount: 金额
            memo: 备注
        
        Returns:
            是否成功
        """
        from_account = self._accounts.get(from_id)
        to_account = self._accounts.get(to_id)
        
        if not from_account or not to_account:
            return False
        
        if from_account.balance < amount:
            return False
        
        # 执行转账
        from_account.balance -= amount
        to_account.balance += amount
        
        # 保存余额到数据库 (TD-004)
        self._save_balance_to_db(from_id)
        self._save_balance_to_db(to_id)
        
        # 记录交易
        tx_hash = self._add_tx(from_id, "transfer", to_id, -amount, memo)
        self._add_tx(to_id, "receive", from_id, amount, memo)
        
        return True
    
    def escrow_lock(self, buyer_id: str, amount: float, job_id: str) -> bool:
        """
        Escrow 锁定（从 Buyer 账户锁定到系统）
        
        Args:
            buyer_id: Buyer 账户 ID
            amount: 锁定金额
            job_id: 关联的 Job ID
        
        Returns:
            是否成功
        """
        buyer = self._accounts.get(buyer_id)
        system = self._accounts.get("system")
        
        if not buyer or not system:
            return False
        
        if buyer.balance < amount:
            return False
        
        # 锁定到系统账户（模拟合约锁定）
        buyer.balance -= amount
        system.balance += amount
        
        # 记录
        self._add_tx(
            buyer_id,
            "escrow_lock",
            "system",
            -amount,
            f"Escrow for job {job_id}"
        )
        self._add_tx(
            "system",
            "escrow_receive",
            buyer_id,
            amount,
            f"Escrow lock for job {job_id}"
        )
        
        return True
    
    def escrow_release(
        self,
        buyer_id: str,
        amount: float,
        job_id: str
    ) -> bool:
        """
        Escrow 释放（退还 Buyer）
        
        Args:
            buyer_id: Buyer 账户 ID
            amount: 退还金额
            job_id: 关联的 Job ID
        
        Returns:
            是否成功
        """
        system = self._accounts.get("system")
        buyer = self._accounts.get(buyer_id)
        
        if not system or not buyer:
            return False
        
        if system.balance < amount:
            return False
        
        system.balance -= amount
        buyer.balance += amount
        
        # 保存余额到数据库 (TD-004)
        self._save_balance_to_db("system")
        self._save_balance_to_db(buyer_id)
        
        self._add_tx(
            "system",
            "escrow_release",
            buyer_id,
            -amount,
            f"Escrow refund for job {job_id}"
        )
        self._add_tx(
            buyer_id,
            "escrow_refund",
            "system",
            amount,
            f"Escrow refund for job {job_id}"
        )
        
        return True
    
    def escrow_settle(
        self,
        job_id: str,
        buyer_id: str,
        node_id: str,
        node_amount: float,
        platform_amount: float
    ) -> bool:
        """
        Escrow 结算
        
        Args:
            job_id: Job ID
            buyer_id: Buyer ID
            node_id: Node ID
            node_amount: Node 收入 (95%)
            platform_amount: 平台手续费 (5%)
        
        Returns:
            是否成功
        """
        system = self._accounts.get("system")
        node = self._accounts.get(node_id)
        
        if not system or not node:
            return False
        
        total = node_amount + platform_amount
        
        if system.balance < total:
            return False
        
        # 结算给 Node
        system.balance -= node_amount
        node.balance += node_amount
        
        # 保存余额到数据库 (TD-004)
        self._save_balance_to_db("system")
        self._save_balance_to_db(node_id)
        
        self._add_tx(
            "system",
            "settle_node",
            node_id,
            -node_amount,
            f"Settlement for job {job_id}"
        )
        self._add_tx(
            node_id,
            "receive_settlement",
            "system",
            node_amount,
            f"Settlement for job {job_id}"
        )
        
        return True
    
    def stake_deposit(self, node_id: str, amount: float) -> bool:
        """
        Stake 存款（Node 存入 Stake）
        
        Args:
            node_id: Node ID
            amount: 存款金额
        
        Returns:
            是否成功
        """
        node = self._accounts.get(node_id)
        
        if not node or node.balance < amount:
            return False
        
        # 模拟 Stake 锁定（从余额转入 Stake 池）
        node.balance -= amount
        
        self._add_tx(
            node_id,
            "stake_deposit",
            "system",
            -amount,
            f"Stake deposit"
        )
        
        return True
    
    def get_all_accounts(self, role: Optional[str] = None) -> List[Account]:
        """获取所有账户，可按角色筛选"""
        if role:
            return [a for a in self._accounts.values() if a.role == role]
        return list(self._accounts.values())
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        accounts = list(self._accounts.values())
        
        return {
            "total_accounts": len(accounts),
            "by_role": {
                "buyer": len([a for a in accounts if a.role == "buyer"]),
                "node": len([a for a in accounts if a.role == "node"]),
                "system": len([a for a in accounts if a.role == "system"]),
            },
            "total_balance": sum(a.balance for a in accounts),
            "total_staked": sum(
                sum(tx.get("amount", 0) for tx in a.txs if tx.get("type") == "stake_deposit" and tx.get("amount", 0) < 0)
                for a in accounts
            ),
        }
    
    def _generate_address(self, account_id: str) -> str:
        """生成钱包地址"""
        hash_input = f"dcm_test_{account_id}_{datetime.utcnow().isoformat()}"
        hash_hex = hashlib.sha256(hash_input.encode()).hexdigest()[:40]
        return f"0x{hash_hex.upper()}"
    
    def _add_tx(
        self,
        account_id: str,
        tx_type: str,
        counterparty: Optional[str],
        amount: float,
        memo: str
    ) -> str:
        """添加交易记录"""
        tx_hash = hashlib.sha256(
            f"{account_id}_{tx_type}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        tx = {
            "tx_hash": tx_hash,
            "type": tx_type,
            "counterparty": counterparty,
            "amount": amount,
            "balance_after": self._accounts.get(account_id).balance if self._accounts.get(account_id) else 0,
            "memo": memo,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if account_id in self._accounts:
            self._accounts[account_id].txs.append(tx)
        
        return tx_hash


# 单例
wallet_service = MockWalletService()
