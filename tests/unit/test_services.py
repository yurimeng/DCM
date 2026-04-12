"""
Unit Tests for DCM - Services
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from src.services.escrow import EscrowService
from src.services.verification import VerificationService
from src.services.matching import MatchingService
from src.services.retry import RetryService, FailureType
from src.models import Job, JobStatus, Node, NodeStatus, Match


class TestEscrowService:
    """测试 Escrow 服务"""
    
    def test_calculate_escrow(self):
        """测试 Escrow 计算公式"""
        # escrow_amount = bid_price × (input + output) / 1M × 1.1
        escrow = EscrowService._calculate_escrow(
            bid_price=0.35,
            input_tokens=2048,
            output_tokens_limit=1024
        )
        
        # 0.35 × (2048 + 1024) / 1_000_000 × 1.1
        expected = 0.35 * 3072 / 1_000_000 * 1.1
        assert abs(escrow - expected) < 0.0000001
    
    def test_calculate_cost(self):
        """测试费用计算"""
        cost = EscrowService._calculate_cost(
            locked_price=0.30,
            actual_tokens=2048
        )
        
        # 0.30 × 2048 / 1_000_000
        expected = 0.30 * 2048 / 1_000_000
        assert abs(cost - expected) < 0.0000001
    
    def test_create_escrow(self):
        """测试创建 Escrow"""
        service = EscrowService()
        escrow = service.create_escrow(
            job_id="test-job-001",
            bid_price=0.35,
            input_tokens=2048,
            output_tokens_limit=1024
        )
        
        assert escrow.job_id == "test-job-001"
        assert escrow.locked_amount > 0
        assert escrow.status.value == "locked"
    
    def test_refund(self):
        """测试退款"""
        service = EscrowService()
        service.create_escrow(
            job_id="test-job-001",
            bid_price=0.35,
            input_tokens=2048,
            output_tokens_limit=1024
        )
        
        escrow = service.refund("test-job-001", "test_reason")
        
        assert escrow.refund_amount == escrow.locked_amount
        assert escrow.refund_reason == "test_reason"


class TestVerificationService:
    """测试验证服务"""
    
    def test_verify_layer1_hash_match(self):
        """测试 Layer 1 哈希验证"""
        service = VerificationService()
        
        import hashlib
        result = "test output"
        result_hash = hashlib.sha256(result.encode()).hexdigest()
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        job.job_id = "test-job-001"
        
        match = Match(
            job_id="test-job-001",
            node_id="test-node-001",
            locked_price=0.30,
        )
        
        passed, reason = service.verify_layer1(
            match=match,
            job=job,
            result=result,
            result_hash=result_hash,
            actual_latency_ms=3000,
            actual_output_tokens=512,
        )
        
        assert passed is True
        assert reason == ""
    
    def test_verify_layer1_hash_mismatch(self):
        """测试 Layer 1 哈希不匹配"""
        service = VerificationService()
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        job.job_id = "test-job-001"
        
        match = Match(
            job_id="test-job-001",
            node_id="test-node-001",
            locked_price=0.30,
        )
        
        passed, reason = service.verify_layer1(
            match=match,
            job=job,
            result="actual result",
            result_hash="wrong_hash",
            actual_latency_ms=3000,
            actual_output_tokens=512,
        )
        
        assert passed is False
        assert "hash_mismatch" in reason
    
    def test_verify_layer1_token_exceeded(self):
        """测试 Layer 1 Token 超限"""
        service = VerificationService()
        
        import hashlib
        result = "test output"
        result_hash = hashlib.sha256(result.encode()).hexdigest()
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        job.job_id = "test-job-001"
        
        match = Match(
            job_id="test-job-001",
            node_id="test-node-001",
            locked_price=0.30,
        )
        
        passed, reason = service.verify_layer1(
            match=match,
            job=job,
            result=result,
            result_hash=result_hash,
            actual_latency_ms=3000,
            actual_output_tokens=2048,  # 超过 limit
        )
        
        assert passed is False
        assert "token_limit_exceeded" in reason
    
    def test_verify_layer1_latency_exceeded(self):
        """测试 Layer 1 延迟超标"""
        service = VerificationService()
        
        import hashlib
        result = "test output"
        result_hash = hashlib.sha256(result.encode()).hexdigest()
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        job.job_id = "test-job-001"
        
        match = Match(
            job_id="test-job-001",
            node_id="test-node-001",
            locked_price=0.30,
        )
        
        passed, reason = service.verify_layer1(
            match=match,
            job=job,
            result=result,
            result_hash=result_hash,
            actual_latency_ms=10000,  # 超过 max_latency × 1.5
            actual_output_tokens=512,
        )
        
        assert passed is False
        assert "latency_exceeded" in reason
    
    def test_check_latency_penalty_normal(self):
        """测试正常延迟"""
        service = VerificationService()
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        
        is_failed, is_mild = service.check_latency_penalty(
            job=job,
            actual_latency_ms=4000,  # 正常范围
        )
        
        assert is_failed is False
        assert is_mild is False
    
    def test_check_latency_penalty_mild(self):
        """测试轻微延迟超标"""
        service = VerificationService()
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        
        is_failed, is_mild = service.check_latency_penalty(
            job=job,
            actual_latency_ms=6000,  # 超过 max 但在 buffer 内
        )
        
        assert is_failed is True
        assert is_mild is True  # 轻微超标
    
    def test_record_violation(self):
        """测试违规记录"""
        service = VerificationService()
        
        should_lock, count = service.record_violation("node-001")
        assert should_lock is False
        assert count == 1
        
        should_lock, count = service.record_violation("node-001")
        assert should_lock is False
        assert count == 2
        
        should_lock, count = service.record_violation("node-001")
        assert should_lock is True  # 3次 → 锁定
        assert count == 3
    
    def test_reset_violations(self):
        """测试重置违规"""
        service = VerificationService()
        
        service.record_violation("node-001")
        service.record_violation("node-001")
        
        service.reset_violations("node-001")
        
        assert service.get_node_violations("node-001") == 0


class TestMatchingService:
    """测试撮合服务"""
    
    def test_add_job(self):
        """测试添加 Job"""
        service = MatchingService()
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        
        service.add_job(job)
        
        assert service.get_pending_jobs_count() == 1
    
    def test_register_node(self):
        """测试注册节点"""
        service = MatchingService()
        
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
            status=NodeStatus.ONLINE,  # 显式设为 ONLINE
        )
        node.node_id = "test-node-001"
        
        service.register_node(node)
        
        assert service.get_online_nodes_count() == 1
    
    def test_match_job_to_node(self):
        """测试撮合 Job 到节点"""
        service = MatchingService()
        
        # 注册节点
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
            status=NodeStatus.ONLINE,
        )
        node.node_id = "test-node-001"
        service.register_node(node)
        
        # 添加 Job
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        service.add_job(job)
        
        # 触发撮合
        match = service.trigger_match(job.job_id)
        
        assert match is not None
        assert match.node_id == "test-node-001"
        assert match.locked_price == 0.30  # 锁定节点 ask_price
        assert service.get_pending_jobs_count() == 0
    
    def test_no_match_price_mismatch(self):
        """测试价格不匹配时不撮合"""
        service = MatchingService()
        
        # 注册节点
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.50,  # 节点报价
            avg_latency=3500,
            region="us-west",
            status=NodeStatus.ONLINE,
        )
        service.register_node(node)
        
        # 添加 Job
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,  # Job 报价低于节点
        )
        service.add_job(job)
        
        # 触发撮合
        match = service.trigger_match(job.job_id)
        
        assert match is None
        assert service.get_pending_jobs_count() == 1  # Job 仍在队列
    
    def test_no_match_latency_exceeded(self):
        """测试延迟超出时不撮合"""
        service = MatchingService()
        
        # 注册节点
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=8000,  # 节点延迟高
            region="us-west",
            status=NodeStatus.ONLINE,
        )
        service.register_node(node)
        
        # 添加 Job
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,  # Job 延迟要求低
            bid_price=0.35,
        )
        service.add_job(job)
        
        # 触发撮合
        match = service.trigger_match(job.job_id)
        
        assert match is None
    
    def test_release_node(self):
        """测试释放节点"""
        service = MatchingService()
        
        node = Node(
            gpu_type="RTX4090",
            vram_gb=24,
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            region="us-west",
            status=NodeStatus.ONLINE,
        )
        node.node_id = "test-node-001"
        service.register_node(node)
        
        # 模拟匹配
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        service.add_job(job)
        service.trigger_match(job.job_id)
        
        assert service.get_online_nodes_count() == 0  # 节点 busy
        
        # 释放节点
        service.release_node("test-node-001")
        
        assert service.get_online_nodes_count() == 1  # 节点恢复 online


class TestRetryService:
    """测试重试服务"""
    
    def test_handle_failure_final(self):
        """测试最终失败（超过重试次数）"""
        from src.services.escrow import escrow_service
        
        service = RetryService()
        
        # 先创建 escrow（使用单例）
        escrow_service.create_escrow(
            job_id="test-job-001",
            bid_price=0.35,
            input_tokens=2048,
            output_tokens_limit=1024,
        )
        
        job = Job(
            model="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=1024,
            max_latency=5000,
            bid_price=0.35,
        )
        job.job_id = "test-job-001"
        job.retry_count = 2  # 已达上限
        
        match = Match(
            job_id="test-job-001",
            node_id="test-node-001",
            locked_price=0.30,
        )
        
        result = service.handle_failure(
            match=match,
            job=job,
            failure_type=FailureType.NODE_OFFLINE,
            reason="timeout",
        )
        
        assert result is None  # 不返回新 Job
        assert job.status == JobStatus.FAILED
