"""
Unit Tests for DCM - Services
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from typing import Optional

from src.services.escrow import EscrowService
from src.services.verification import VerificationService
from src.services.matching import MatchingService
from src.services.retry import RetryService, FailureType
from src.services.queue import JobQueueService
from src.models import Job, JobStatus, Node, NodeStatus, Match


class MockJobQueue(JobQueueService):
    """Mock Job Queue for testing"""
    
    def __init__(self):
        self._jobs = {}
        self._heap = []
        self._stats = {"enqueued": 0, "dequeued": 0, "completed": 0}
    
    def enqueue(self, job_data: dict) -> str:
        job_id = job_data["job_id"]
        self._jobs[job_id] = job_data
        self._heap.append(job_id)
        self._stats["enqueued"] += 1
        return job_id
    
    def dequeue(self, timeout: float = None) -> Optional[dict]:
        if self._heap:
            job_id = self._heap.pop(0)
            self._stats["dequeued"] += 1
            return self._jobs.get(job_id)
        return None
    
    def peek(self, count: int = 10) -> list:
        return [self._jobs.get(jid) for jid in self._heap[:count] if jid in self._jobs]
    
    def acknowledge(self, job_id: str) -> bool:
        self._stats["completed"] += 1
        return True
    
    def retry(self, job_id: str, delay: float = 0) -> bool:
        if job_id in self._jobs and job_id not in self._heap:
            self._heap.append(job_id)
        return True
    
    def dead_letter(self, job_id: str, reason: str) -> bool:
        return True
    
    def get_stats(self):
        from src.services.queue.job_queue import QueueStats
        return QueueStats(
            total_enqueued=self._stats["enqueued"],
            total_dequeued=self._stats["dequeued"],
            total_completed=self._stats["completed"],
            current_size=len(self._heap)
        )
    
    def get_pending_jobs(self) -> list:
        return [self._jobs.get(jid) for jid in self._heap if jid in self._jobs]
    
    def get_dead_letter_jobs(self) -> list:
        return []
    
    def requeue_dead_letter(self, job_id: str) -> bool:
        return True
    
    def size(self) -> int:
        return len(self._heap)
    
    def clear(self) -> None:
        self._jobs.clear()
        self._heap.clear()
        self._stats = {"enqueued": 0, "dequeued": 0, "completed": 0}


class TestEscrowService:
    """测试 Escrow 服务"""
    
    def test_calculate_escrow(self):
        """测试 Escrow 计算公式"""
        # escrow_amount = bid_price × (input + output) / 1M × 1.1
        escrow = EscrowService._calculate_escrow(
            bid_price=0.35,
            input_tokens=2048,
            output_tokens_limit=100
        )
        
        # 0.35 × (2048 + 100) / 1_000_000 × 1.1
        expected = 0.35 * 2148 / 1_000_000 * 1.1
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
            output_tokens_limit=100
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
            output_tokens_limit=100
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
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
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
            actual_output_tokens=100,  # 不超过 limit
        )
        
        assert passed is True
        assert reason == ""
    
    def test_verify_layer1_hash_mismatch(self):
        """测试 Layer 1 哈希不匹配"""
        service = VerificationService()
        
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
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
            actual_output_tokens=100,  # 不超过 limit
        )
        
        assert passed is False
        assert "hash_mismatch" in reason
        """测试 Layer 1 Token 超限"""
        service = VerificationService()
        
        import hashlib
        result = "test output"
        result_hash = hashlib.sha256(result.encode()).hexdigest()
        
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
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
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
            max_latency=5000,  # Job 限制 5s
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
            actual_latency_ms=8000,  # 超过 max_latency*1.5=7500 限制
            actual_output_tokens=100,  # 不超过 limit
        )
        
        assert passed is False
        assert "latency_exceeded" in reason
    
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
        mock_queue = MockJobQueue()
        service = MatchingService(queue=mock_queue)
        
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.35,
        )
        
        service.add_job(job)
        
        assert service.get_pending_jobs_count() == 1
    
    def test_register_node(self):
        """测试注册节点"""
        service = MatchingService()
        
        node = Node(
            node_id="test-node-001",
            user_id="user_test",
            gpu_type="RTX4090",
            gpu_vram_gb=24,
            vram_gb=24,
            gpu_qty=1,
            os_name="Linux",
            os_version="Ubuntu 22.04",
            runtime="ollama",
            model="llama3-8b",
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            avg_success_rate=0.95,
            avg_quality_score=0.9,
            region="us-west",
            status=NodeStatus.ONLINE,
        )
        
        service.register_node(node)
        
        assert service.get_online_nodes_count() == 1
    
    def test_match_job_to_node(self):
        """测试撮合 Job 到节点"""
        mock_queue = MockJobQueue()
        service = MatchingService(queue=mock_queue)
        
        # 注册节点 (DCM v3.2: 指定 queue_info)
        node = Node(
            node_id="test-node-001",
            user_id="user_test",
            gpu_type="RTX4090",
            gpu_vram_gb=24,
            vram_gb=24,
            gpu_qty=1,
            os_name="Linux",
            os_version="Ubuntu 22.04",
            runtime="ollama",
            model="llama3-8b",
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            avg_success_rate=0.95,
            avg_quality_score=0.9,
            region="us-west",
            status=NodeStatus.ONLINE,
            # DCM v3.2: 队列配置
            queue_info={"max_queue": 5000, "available_queue": 5000},
        )
        service.register_node(node)
        
        # 添加 Job (total tokens = 3072 < 5000)
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
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
        mock_queue = MockJobQueue()
        service = MatchingService(queue=mock_queue)
        
        # 注册节点
        node = Node(
            node_id="test-node-002",
            user_id="user_test",
            gpu_type="RTX4090",
            gpu_vram_gb=24,
            vram_gb=24,
            gpu_qty=1,
            os_name="Linux",
            os_version="Ubuntu 22.04",
            runtime="ollama",
            model="llama3-8b",
            model_support=["llama3-8b"],
            ask_price=0.50,  # 节点报价
            avg_latency=3500,
            avg_success_rate=0.95,
            avg_quality_score=0.9,
            region="us-west",
            status=NodeStatus.ONLINE,
        )
        service.register_node(node)
        
        # 添加 Job
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
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
        mock_queue = MockJobQueue()
        service = MatchingService(queue=mock_queue)
        
        # 注册节点
        node = Node(
            node_id="test-node-003",
            user_id="user_test",
            gpu_type="RTX4090",
            gpu_vram_gb=24,
            vram_gb=24,
            gpu_qty=1,
            os_name="Linux",
            os_version="Ubuntu 22.04",
            runtime="ollama",
            model="llama3-8b",
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=8000,  # 节点延迟高
            avg_success_rate=0.95,
            avg_quality_score=0.9,
            region="us-west",
            status=NodeStatus.ONLINE,
        )
        service.register_node(node)
        
        # 添加 Job
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
            max_latency=5000,  # Job 延迟要求低
            bid_price=0.35,
        )
        service.add_job(job)
        
        # 触发撮合
        match = service.trigger_match(job.job_id)
        
        assert match is None
    
    def test_release_node(self):
        """测试释放节点"""
        mock_queue = MockJobQueue()
        service = MatchingService(queue=mock_queue)
        
        # 注册节点 (DCM v3.2: 指定 queue_info)
        node = Node(
            node_id="test-node-001",
            user_id="user_test",
            gpu_type="RTX4090",
            gpu_vram_gb=24,
            vram_gb=24,
            gpu_qty=1,
            os_name="Linux",
            os_version="Ubuntu 22.04",
            runtime="ollama",
            model="llama3-8b",
            model_support=["llama3-8b"],
            ask_price=0.30,
            avg_latency=3500,
            avg_success_rate=0.95,
            avg_quality_score=0.9,
            region="us-west",
            status=NodeStatus.ONLINE,
            # DCM v3.2: 队列配置
            queue_info={"max_queue": 5000, "available_queue": 5000},
        )
        service.register_node(node)
        
        # 模拟匹配 (total tokens = 3072 < 5000)
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
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
            output_tokens_limit=100,
        )
        
        job = Job(
            model_requirement="llama3-8b",
            input_tokens=2048,
            output_tokens_limit=100,
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
