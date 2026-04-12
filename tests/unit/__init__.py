"""
Unit Tests for DCM
"""

import pytest
from src.models import Job, JobStatus, Node, NodeStatus, Escrow
from src.services import escrow_service, matching_service


class TestJobModel:
    """测试 Job 模型"""
    
    def test_job_creation(self):
        """测试 Job 创建"""
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        
        assert job.model == "llama3-8b"
        assert job.input_tokens == 2048
        assert job.status == JobStatus.PENDING
    
    def test_invalid_model(self):
        """测试无效模型"""
        with pytest.raises(ValueError):
            Job(
                model="gpt-4",  # MVP 不支持
                input_tokens=2048,
                output_tokens_limit=1024,
                max_latency=5000,
                bid_price=0.35,
            )


class TestNodeModel:
    """测试 Node 模型"""
    
    def test_node_personal_tier(self):
        """测试 Personal 分级"""
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        assert node.stake_tier.value == "personal"
        assert node.stake_required == 50.0
    
    def test_node_professional_tier(self):
        """测试 Professional 分级"""
        node = Node(
            gpu_type="A100",
            vram_gb=40,
            model_support=["llama3-8b"],
            ask_price=0.25,
            avg_latency=2500,
            region="us-east",
        )
        
        assert node.stake_tier.value == "professional"
        assert node.stake_required == 200.0
    
    def test_node_datacenter_tier(self):
        """测试 Data Center 分级"""
        node = Node(
            gpu_type="A100-80G",
            vram_gb=80,
            model_support=["llama3-8b"],
            ask_price=0.20,
            avg_latency=2000,
            region="eu-central",
        )
        
        assert node.stake_tier.value == "datacenter"
        assert node.stake_required == 1000.0


class TestEscrowService:
    """测试 Escrow 服务"""
    
    def test_calculate_escrow(self):
        """测试 Escrow 计算公式"""
        # escrow = bid_price × (input + output) / 1M × 1.1
        # = 0.35 × (2048 + 1024) / 1M × 1.1
        # = 0.35 × 3072 / 1M × 1.1
        # = 0.001183 USDC
        
        escrow = escrow_service.create_escrow(
            job_id="test-job-1",
            bid_price=0.35,
            input_tokens=2048,
            output_tokens_limit=1024,
        )
        
        assert escrow.locked_amount == pytest.approx(0.0011832, rel=0.0001)
        assert escrow.status.value == "locked"
    
    def test_escrow_settlement(self):
        """测试结算"""
        from src.models import SettlementRequest
        
        # 创建 Escrow
        escrow = escrow_service.create_escrow(
            job_id="test-job-2",
            bid_price=0.30,
            input_tokens=2048,
            output_tokens_limit=1024,
        )
        escrow.match_id = "test-match-1"
        
        # 执行结算
        request = SettlementRequest(
            match_id="test-match-1",
            actual_tokens=2900,
            locked_price=0.30,
            verification_passed=True,
        )
        
        settled = escrow_service.execute_settlement(request)
        
        # 验证结算金额
        # actual_cost = 0.30 × 2900 / 1M = 0.00087
        # node_earn = 0.00087 × 0.95 = 0.0008265
        # platform_fee = 0.00087 × 0.05 = 0.0000435
        
        assert settled.actual_cost == pytest.approx(0.00087, rel=0.001)
        assert settled.node_earn == pytest.approx(0.0008265, rel=0.001)
        assert settled.platform_fee == pytest.approx(0.0000435, rel=0.001)
        assert settled.status.value == "settled"


class TestMatchingService:
    """测试撮合服务"""
    
    def test_matching_basic(self):
        """测试基本撮合"""
        # 创建 Job
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        
        # 创建 Node
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        # 注册
        matching_service.add_job(job)
        matching_service.register_node(node)
        matching_service.update_node_status(node.node_id, NodeStatus.ONLINE)
        
        # 触发撮合
        match = matching_service.trigger_match(job.job_id)
        
        assert match is not None
        assert match.job_id == job.job_id
        assert match.node_id == node.node_id
        assert match.locked_price == 0.30  # 锁定价格
        assert job.status == JobStatus.MATCHED
        assert node.status == NodeStatus.BUSY
    
    def test_price_mismatch(self):
        """测试价格不匹配"""
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.20,  # bid < ask
        )
        
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        matching_service.add_job(job)
        matching_service.register_node(node)
        matching_service.update_node_status(node.node_id, NodeStatus.ONLINE)
        
        # 应该撮合失败
        match = matching_service.trigger_match(job.job_id)
        assert match is None
