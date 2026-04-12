"""
Unit Tests for Mock Wallet Service
"""

import pytest
from src.core.wallet import MockWalletService, Account


class TestMockWalletService:
    """测试模拟钱包服务"""
    
    def setup_method(self):
        """每个测试前重置钱包"""
        self.wallet = MockWalletService()
    
    def test_initialize_test_accounts(self):
        """测试初始化测试账户"""
        accounts = self.wallet.initialize_test_accounts()
        
        assert len(accounts) == 7  # 3 buyers + 3 nodes + 1 system
        
        # 验证 Buyer 账户
        assert "buyer-001" in accounts
        assert accounts["buyer-001"].balance == 100.0
        assert accounts["buyer-001"].role == "buyer"
        
        # 验证 Node 账户
        assert "node-001" in accounts
        assert accounts["node-001"].balance == 50.0
        assert accounts["node-001"].role == "node"
        
        # 验证 System 账户
        assert "system" in accounts
        assert accounts["system"].role == "system"
    
    def test_create_account(self):
        """测试创建账户"""
        account = self.wallet.create_account(
            role="buyer",
            initial_balance=100.0
        )
        
        assert account.account_id is not None
        assert account.balance == 100.0
        assert account.role == "buyer"
        assert account.address.startswith("0x")
    
    def test_get_account(self):
        """测试获取账户"""
        self.wallet.initialize_test_accounts()
        
        account = self.wallet.get_account("buyer-001")
        assert account is not None
        assert account.account_id == "buyer-001"
    
    def test_get_account_not_found(self):
        """测试获取不存在的账户"""
        account = self.wallet.get_account("nonexistent")
        assert account is None
    
    def test_transfer_success(self):
        """测试成功转账"""
        self.wallet.initialize_test_accounts()
        
        success = self.wallet.transfer(
            from_id="buyer-001",
            to_id="buyer-002",
            amount=10.0,
            memo="Test transfer"
        )
        
        assert success is True
        assert self.wallet.get_balance("buyer-001") == 90.0
        assert self.wallet.get_balance("buyer-002") == 110.0
    
    def test_transfer_insufficient_balance(self):
        """测试余额不足转账"""
        self.wallet.initialize_test_accounts()
        
        success = self.wallet.transfer(
            from_id="buyer-001",
            to_id="buyer-002",
            amount=200.0,  # 超过余额
            memo="Test transfer"
        )
        
        assert success is False
        assert self.wallet.get_balance("buyer-001") == 100.0  # 未变化
    
    def test_transfer_invalid_account(self):
        """测试无效账户转账"""
        self.wallet.initialize_test_accounts()
        
        success = self.wallet.transfer(
            from_id="nonexistent",
            to_id="buyer-001",
            amount=10.0
        )
        
        assert success is False
    
    def test_escrow_lock(self):
        """测试 Escrow 锁定"""
        self.wallet.initialize_test_accounts()
        
        success = self.wallet.escrow_lock(
            buyer_id="buyer-001",
            amount=0.001,
            job_id="job-test-001"
        )
        
        assert success is True
        assert self.wallet.get_balance("buyer-001") == 99.999
        assert self.wallet.get_balance("system") == 0.001
    
    def test_escrow_release(self):
        """测试 Escrow 释放（退款）"""
        self.wallet.initialize_test_accounts()
        
        # 先锁定
        self.wallet.escrow_lock(
            buyer_id="buyer-001",
            amount=0.001,
            job_id="job-test-001"
        )
        
        # 再释放
        success = self.wallet.escrow_release(
            buyer_id="buyer-001",
            amount=0.001,
            job_id="job-test-001"
        )
        
        assert success is True
        assert self.wallet.get_balance("buyer-001") == 100.0
        assert self.wallet.get_balance("system") == 0.0
    
    def test_escrow_settle(self):
        """测试 Escrow 结算"""
        self.wallet.initialize_test_accounts()
        
        # 锁定 Escrow
        self.wallet.escrow_lock(
            buyer_id="buyer-001",
            amount=0.001,
            job_id="job-test-001"
        )
        
        # 结算 (95% 给 Node, 5% 给 Platform)
        # 注意: platform_amount 留在 system 账户作为手续费
        success = self.wallet.escrow_settle(
            job_id="job-test-001",
            buyer_id="buyer-001",
            node_id="node-001",
            node_amount=0.00095,
            platform_amount=0.00005
        )
        
        assert success is True
        assert abs(self.wallet.get_balance("system") - 0.00005) < 0.000001  # 手续费留存在系统账户
        assert abs(self.wallet.get_balance("node-001") - 50.00095) < 0.000001
    
    def test_stake_deposit(self):
        """测试 Stake 存款"""
        self.wallet.initialize_test_accounts()
        
        success = self.wallet.stake_deposit(
            node_id="node-001",
            amount=50.0
        )
        
        assert success is True
        assert self.wallet.get_balance("node-001") == 0.0  # 全部存款
    
    def test_get_all_accounts(self):
        """测试获取所有账户"""
        self.wallet.initialize_test_accounts()
        
        all_accounts = self.wallet.get_all_accounts()
        assert len(all_accounts) == 7
        
        buyers = self.wallet.get_all_accounts(role="buyer")
        assert len(buyers) == 3
        
        nodes = self.wallet.get_all_accounts(role="node")
        assert len(nodes) == 3
    
    def test_get_stats(self):
        """测试获取统计"""
        self.wallet.initialize_test_accounts()
        
        stats = self.wallet.get_stats()
        
        assert stats["total_accounts"] == 7
        assert stats["by_role"]["buyer"] == 3
        assert stats["by_role"]["node"] == 3
        # 3 buyers × 100 + 3 nodes × 50 + 1 system × 0 = 450
        assert stats["total_balance"] == 450.0


class TestAccount:
    """测试 Account 模型"""
    
    def test_account_to_dict(self):
        """测试账户转字典"""
        account = Account(
            account_id="test-001",
            address="0x1234567890",
            balance=100.0,
            role="buyer"
        )
        
        data = account.to_dict()
        
        assert data["account_id"] == "test-001"
        assert data["address"] == "0x1234567890"
        assert data["balance"] == 100.0
        assert data["role"] == "buyer"
        assert "tx_count" in data
