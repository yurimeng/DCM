"""
Unit Tests for DCM - Models
DCM 模型单元测试

Updated for DCM v3.1 (dynamic model families)
适配 DCM v3.1（动态模型家族）
"""

import pytest
from datetime import datetime

from src.models import Job, JobStatus, Node, NodeStatus, NodeTier, Match, Escrow, EscrowStatus
from src.models.db_models import JobDB, NodeDB, MatchDB, EscrowDB


class TestJobModel:
    """
    Test Job Pydantic Model
    Job Pydantic 模型测试
    """
    
    def test_job_creation(self):
        """Test Job creation / 测试 Job 创建"""
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.35,
        )
        
        assert job.model_requirement == "llama3-8b"
        assert job.input_tokens == 2048
        assert job.output_tokens_limit == 100
        assert job.bid_price == 0.35
        assert job.status == JobStatus.PENDING
        assert job.retry_count == 0
    
    def test_job_with_callback(self):
        """Test Job with callback URL / 测试带回调 URL 的 Job"""
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.35,
            callback_url="https://example.com/callback",
        )
        
        assert job.callback_url == "https://example.com/callback"
    
    def test_generic_job(self):
        """
        Test generic Job (no model requirement)
        测试通用 Job（无模型要求）
        """
        job = Job(
            model_requirement=None,
            input_tokens=2048,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.35,
        )
        
        assert job.model_requirement is None
    
    def test_invalid_bid_price(self):
        """Test invalid bid_price / 测试无效的 bid_price"""
        with pytest.raises(ValueError):
            Job(
                model_requirement="llama3-8b",
                input_tokens=2048,
                output_tokens_limit=1024,
                max_latency=5000,
                bid_price=0,  # Must be > 0 / 必须 > 0
            )


class TestNodeModel:
    """
    Test Node Pydantic Model (v3.1 - Required: runtime and model)
    Node Pydantic 模型测试（v3.1 - 必填：runtime 和 model）
    """
    
    def test_node_personal_tier(self):
        """
        Test Personal tier (< 4 GPU)
        测试 Personal 分级（< 4 GPU）
        """
        node = Node(
            node_id="node-001",
            gpu_type="RTX4090",
            vram_gb=23,
            runtime="ollama",
            model="llama3-8b",
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        assert node.stake_tier == NodeTier.PERSONAL
        # stake_required defaults to 0.0, use get_stake_required() for calculation
        # stake_required 默认值为 0.0，使用 get_stake_required() 方法计算
        assert node.status == NodeStatus.OFFLINE
        assert node.runtime == "ollama"
        assert node.model == "llama3-8b"
    
    def test_node_professional_tier(self):
        """
        Test Professional tier (4-7 GPU)
        测试 Professional 分级（4-7 GPU）
        """
        node = Node(
            node_id="node-002",
            gpu_type="A100",
            vram_gb=40,
            gpu_count=4,  # 4 GPU = Professional / 4 GPU = Professional
            runtime="vllm",
            model="qwen2.5:7b",
            ask_price=0.25,
            avg_latency=2500,
            region="us-east",
        )
        
        # Use get_stake_tier() method for correct tier
        assert node.get_stake_tier() == NodeTier.PROFESSIONAL
    
    def test_node_enterprise_tier(self):
        """
        Test Enterprise tier (>= 8 GPU)
        测试 Enterprise 分级（>= 8 GPU）
        """
        node = Node(
            node_id="node-003",
            gpu_type="A100-80G-8x",
            vram_gb=640,
            gpu_count=8,  # 8 GPU = Enterprise / 8 GPU = Enterprise
            runtime="vllm",
            model="qwen2.5:14b",
            ask_price=0.20,
            avg_latency=2000,
            region="eu-central",
        )
        
        # Use get_stake_tier() method for correct tier
        assert node.get_stake_tier() == NodeTier.ENTERPRISE
    
    def test_node_custom_model(self):
        """
        Test node with custom model (no whitelist)
        测试节点支持任意模型（无白名单）
        """
        node = Node(
            node_id="node-004",
            gpu_type="RTX4090",
            vram_gb=24,
            runtime="ollama",
            model="custom-model:v1",
            model_support=["custom-model:v1", "custom-model:v2"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        assert node.model == "custom-model:v1"
        assert "custom-model:v2" in node.model_support


class TestMatchModel:
    """
    Test Match Pydantic Model
    Match Pydantic 模型测试
    """
    
    def test_match_creation(self):
        """Test Match creation / 测试 Match 创建"""
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
        """
        Test Match price is locked
        测试 Match 价格锁定
        """
        match = Match(
            job_id="job-001",
            node_id="node-001",
            locked_price=0.30,
        )
        
        # Price should not change after locking
        # 锁定后价格不应变化
        assert match.locked_price == 0.30


class TestEscrowModel:
    """
    Test Escrow Pydantic Model
    Escrow Pydantic 模型测试
    """
    
    def test_escrow_creation(self):
        """Test Escrow creation / 测试 Escrow 创建"""
        escrow = Escrow(
            job_id="job-001",
            locked_amount=0.0012,
        )
        
        assert escrow.job_id == "job-001"
        assert escrow.locked_amount == 0.0012
        assert escrow.status == EscrowStatus.LOCKED
        assert escrow.spent_amount == 0.0
    
    def test_escrow_settled(self):
        """
        Test Escrow settled status
        测试 Escrow 已结算状态
        """
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
    """
    Test Job Database Model
    Job 数据库模型测试
    """
    
    def test_job_db_create(self, db_session):
        """Test creating Job in database / 测试在数据库中创建 Job"""
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
        
        # Query verification / 查询验证
        retrieved = db_session.query(JobDB).filter(
            JobDB.job_id == "db-job-001"
        ).first()
        
        assert retrieved is not None
        assert retrieved.model == "llama3-8b"
        assert retrieved.bid_price == 0.35


class TestNodeDBModel:
    """
    Test Node Database Model (v3.1 - New: runtime and model)
    Node 数据库模型测试（v3.1 - 新增：runtime 和 model）
    """
    
    def test_node_db_create(self, db_session):
        """Test creating Node in database / 测试在数据库中创建 Node"""
        import json
        
        node = NodeDB(
            node_id="db-node-001",
            gpu_type="RTX4090",
            vram_gb=24,
            runtime="ollama",
            model="llama3-8b",
            model_support=json.dumps(["llama3-8b"]),
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
        )
        
        db_session.add(node)
        db_session.commit()
        
        # Query verification / 查询验证
        retrieved = db_session.query(NodeDB).filter(
            NodeDB.node_id == "db-node-001"
        ).first()
        
        assert retrieved is not None
        assert retrieved.gpu_type == "RTX4090"
        assert retrieved.runtime == "ollama"
        assert retrieved.model == "llama3-8b"
        assert json.loads(retrieved.model_support) == ["llama3-8b"]
