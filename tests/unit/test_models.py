"""
Unit Tests for DCM - Models
"""

import pytest
from datetime import datetime

from src.models import Job, JobStatus, Node, NodeStatus, NodeTier, Match, Escrow, EscrowStatus
from src.models.db_models import JobDB, NodeDB, MatchDB, EscrowDB


class TestJobModel:
    """测试 Job Pydantic 模型"""
    
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
        assert job.output_tokens_limit == 1024
        assert job.bid_price == 0.35
        assert job.status == JobStatus.PENDING
        assert job.retry_count == 0
    
    def test_job_with_callback(self):
        """测试带回调 URL 的 Job"""
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
            callback_url="https://example.com/callback",
        )
        
        assert job.callback_url == "https://example.com/callback"
    
    def test_invalid_model_raises_error(self):
        """测试无效模型抛出错误"""
        with pytest.raises(ValueError) as exc_info:
            Job(
                model="gpt-4",  # MVP 不支持
                input_tokens=2048,
                output_tokens_limit=1024,
                max_latency=5000,
                bid_price=0.35,
            )
        
        assert "llama3-8b" in str(exc_info.value)
    
    def test_invalid_bid_price(self):
        """测试无效的 bid_price"""
        with pytest.raises(ValueError):
            Job(
                model="llama3-8b",
                input_tokens=2048,
                output_tokens_limit=1024,
                max_latency=5000,
                bid_price=0,  # 必须 > 0
            )


class TestNodeModel:
    """测试 Node Pydantic 模型"""
    
    def test_node_personal_tier(self):
        """测试 Personal 分级（< 24 GB）"""
        node = Node(
            gpu_type="RTX4090",
            vram_gb=23,  # < 24 GB 才是 Personal
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        assert node.stake_tier == NodeTier.PERSONAL
        assert node.stake_required == 50.0
        assert node.status == NodeStatus.OFFLINE
    
    def test_node_professional_tier(self):
        """测试 Professional 分级（24-80 GB）"""
        node = Node(
            gpu_type="A100",
            vram_gb=40,
            model_support=["llama3-8b"],
            ask_price=0.25,
            avg_latency=2500,
            region="us-east",
        )
        
        assert node.stake_tier == NodeTier.PROFESSIONAL
        assert node.stake_required == 200.0
    
    def test_node_datacenter_tier(self):
        """测试 Data Center 分级（> 80 GB）"""
        node = Node(
            gpu_type="A100-80G-8x",
            vram_gb=640,  # 8x A100 80GB
            model_support=["llama3-8b"],
            ask_price=0.20,
            avg_latency=2000,
            region="eu-central",
        )
        
        assert node.stake_tier == NodeTier.DATA_CENTER
        assert node.stake_required == 1000.0
    
    def test_node_invalid_model_support(self):
        """测试节点必须支持 llama3-8b"""
        with pytest.raises(ValueError) as exc_info:
            Node(
                gpu_type="RTX4090",
                vram_gb=24,
                model_support=["gpt-4"],  # MVP 不支持
                ask_price=0.30,
                avg_latency=3500,
                region="us-west",
            )
        
        assert "llama3-8b" in str(exc_info.value)


class TestMatchModel:
    """测试 Match Pydantic 模型"""
    
    def test_match_creation(self):
        """测试 Match 创建"""
        match = Match(
            job_id="job-001",
            node_id="node-001",
            locked_price=0.30,
        )
        
        assert match.job_id == "job-001"
        assert match.node_id == "node-001"
        assert match.locked_price == 0.30
        assert match.verified is False
        assert match.settled is False
    
    def test_match_price_locked(self):
        """测试 Match 价格锁定"""
        match = Match(
            job_id="job-001",
            node_id="node-001",
            locked_price=0.30,
        )
        
        # 价格锁定后不应变化
        assert match.locked_price == 0.30


class TestEscrowModel:
    """测试 Escrow Pydantic 模型"""
    
    def test_escrow_creation(self):
        """测试 Escrow 创建"""
        escrow = Escrow(
            job_id="job-001",
            locked_amount=0.0012,
        )
        
        assert escrow.job_id == "job-001"
        assert escrow.locked_amount == 0.0012
        assert escrow.status == EscrowStatus.LOCKED
        assert escrow.spent_amount == 0.0
    
    def test_escrow_settled(self):
        """测试 Escrow 已结算状态"""
        escrow = Escrow(
            job_id="job-001",
            locked_amount=0.0012,
        )
        
        escrow.status = EscrowStatus.SETTLED
        escrow.spent_amount = 0.0008
        escrow.refund_amount = 0.0004
        
        assert escrow.status == EscrowStatus.SETTLED
        assert escrow.refund_amount == 0.0004


class TestJobDBModel:
    """测试 Job 数据库模型"""
    
    def test_job_db_create(self, db_session):
        """测试数据库中创建 Job"""
        job = JobDB(
            job_id="db-job-001",
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        
        db_session.add(job)
        db_session.commit()
        
        # 查询验证
        retrieved = db_session.query(JobDB).filter(
            JobDB.job_id == "db-job-001"
        ).first()
        
        assert retrieved is not None
        assert retrieved.model == "llama3-8b"
        assert retrieved.bid_price == 0.35


class TestNodeDBModel:
    """测试 Node 数据库模型"""
    
    def test_node_db_create(self, db_session):
        """测试数据库中创建 Node"""
        import json
        
        node = NodeDB(
            node_id="db-node-001",
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=json.dumps(["llama3-8b"]),
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        db_session.add(node)
        db_session.commit()
        
        # 查询验证
        retrieved = db_session.query(NodeDB).filter(
            NodeDB.node_id == "db-node-001"
        ).first()
        
        assert retrieved is not None
        assert retrieved.gpu_type == "RTX4090"
        assert json.loads(retrieved.model_support) == ["llama3-8b"]
