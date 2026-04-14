"""
Phase 1 Tests - DCM v3.1
测试核心数据模型
"""

import pytest
from datetime import datetime

from src.models import (
    Job, JobStatus, 
    Slot, SlotStatus, LockType, JobSet,
    Match, MatchCreate,
)
from src.models.cluster import ModelInfo, PricingInfo, PerformanceInfo, CapacityInfo
from src.services.compatibility import CompatibilityMatrix, CompatibilityLevel


class TestJobModel:
    """Job 模型测试"""
    
    def test_job_creation(self):
        """创建 Job"""
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        assert job.job_id == "job_001"
        assert job.model_requirement == "qwen3-8b"
        assert job.status == JobStatus.PENDING
        assert job.input_tokens == 100
    
    def test_job_status_transitions(self):
        """Job 状态转换"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        # PENDING → MATCHED
        job.status = JobStatus.MATCHED
        job.matched_at = datetime.utcnow()
        assert job.status == JobStatus.MATCHED
        
        # MATCHED → PRE_LOCKED
        job.status = JobStatus.PRE_LOCKED
        job.pre_locked_at = datetime.utcnow()
        assert job.status == JobStatus.PRE_LOCKED
        
        # PRE_LOCKED → RESERVED
        job.status = JobStatus.RESERVED
        job.reserved_at = datetime.utcnow()
        
        # RESERVED → DISPATCHED
        job.status = JobStatus.DISPATCHED
        job.dispatched_at = datetime.utcnow()
        
        # DISPATCHED → RUNNING
        job.status = JobStatus.RUNNING
        
        # RUNNING → COMPLETED
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        assert job.is_terminal() == True
    
    def test_job_retry(self):
        """Job 重试"""
        job = Job(
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
            max_retries=2,
        )
        
        assert job.can_retry() == False  # 初始不是 FAILED 状态
        
        job.status = JobStatus.FAILED
        assert job.can_retry() == True
        
        job.retry_count = 1
        assert job.can_retry() == True
        
        job.retry_count = 2
        assert job.can_retry() == False  # 达到最大重试次数


class TestSlotModel:
    """Slot 模型测试 (DCM v3.1)"""
    
    def test_slot_creation(self):
        """创建 Slot"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        assert slot.cluster_id == "slot_001"
        assert slot.model.name == "qwen3-8b"
        assert slot.status == SlotStatus.FREE
    
    def test_slot_multi_job_capacity(self):
        """Slot 多 Job 容量"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        assert slot.capacity.max_concurrency == 4
        assert slot.capacity.available_capacity == 4
        assert slot.capacity.is_full == False
    
    def test_slot_pre_lock(self):
        """Slot Pre-Lock"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Pre-Lock
        assert slot.pre_lock("job_001", ttl_ms=5000) == True
        assert slot.status == SlotStatus.PRE_LOCKED
        assert len(slot.locks) == 1
        assert slot.locks[0].lock_type == LockType.PRE_LOCK
        
        # 确认
        assert slot.confirm_pre_lock("job_001") == True
        assert slot.locks[0].lock_type == LockType.HARD_LOCK
        assert "job_001" in slot.job_sets.reserved
        assert slot.capacity.reserved_jobs == 1
    
    def test_slot_multi_pre_lock(self):
        """Slot 多 Pre-Lock"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Pre-Lock 3 个 Job
        for i in range(3):
            assert slot.pre_lock(f"job_{i+1:03d}") == True
        
        assert len(slot.locks) == 3
        assert slot.capacity.pre_locked_jobs == 3
        assert slot.capacity.available_capacity == 1
        
        # 第 4 个成功 (总共 4 个 = max_concurrency)
        assert slot.pre_lock("job_004") == True
        assert len(slot.locks) == 4
        assert slot.capacity.available_capacity == 0
        
        # 第 5 个失败 (超出 max_concurrency)
        assert slot.pre_lock("job_005") == False
    
    def test_slot_lock_release(self):
        """Slot Lock 释放"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # 完整的 Pre-Lock 流程
        slot.pre_lock("job_001")
        slot.confirm_pre_lock("job_001")
        slot.start_running("job_001")
        
        assert slot.capacity.active_jobs == 1
        
        # 完成
        slot.finish_job("job_001")
        
        assert len(slot.locks) == 0
        assert slot.capacity.active_jobs == 0
        assert slot.status == SlotStatus.FREE
    
    def test_slot_status_update(self):
        """Slot 状态自动更新"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # FREE → PRE_LOCKED
        slot.pre_lock("job_001")
        assert slot.status == SlotStatus.PRE_LOCKED
        
        # PRE_LOCKED → PARTIALLY_RESERVED
        slot.confirm_pre_lock("job_001")
        assert slot.status == SlotStatus.PARTIALLY_RESERVED


class TestMatchModel:
    """Match 模型测试"""
    
    def test_match_creation(self):
        """创建 Match"""
        match = Match(
            job_id="job_001",
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            locked_price=0.5,
            model="qwen3-8b",
        )
        
        assert match.job_id == "job_001"
        assert match.cluster_id == "slot_001"
        assert match.node_id == "node_001"
        assert match.worker_id == "worker_001"
        assert match.model == "qwen3-8b"


class TestCompatibilityMatrix:
    """兼容性矩阵测试"""
    
    def test_exact_match(self):
        """精确匹配"""
        matrix = CompatibilityMatrix()
        
        score = matrix.get_compatibility("qwen3-8b", "qwen3-8b")
        assert score == 1.0
        
        score = matrix.get_compatibility("qwen3:8b", "qwen3-8b")
        assert score == 1.0
    
    def test_version_coverage(self):
        """版本覆盖"""
        matrix = CompatibilityMatrix()
        
        # 高版本 Slot 可服务低版本 Job
        score = matrix.get_compatibility("qwen3-8b", "qwen3.5-8b")
        assert score >= 0.8  # FAMILY level
        
        # 低版本 Slot 无法服务高版本 Job
        score = matrix.get_compatibility("qwen3.5-8b", "qwen3-8b")
        assert score == 0.0
    
    def test_size_coverage(self):
        """Size 覆盖"""
        matrix = CompatibilityMatrix()
        
        # 大模型 Slot 可服务小模型 Job
        score = matrix.get_compatibility("qwen3-7b", "qwen3-14b")
        assert score >= 0.8  # FAMILY level
        
        # 小模型 Slot 无法服务大模型 Job
        score = matrix.get_compatibility("qwen3-14b", "qwen3-7b")
        assert score == 0.0
    
    def test_cross_family(self):
        """跨家族"""
        matrix = CompatibilityMatrix()
        
        # 不同家族
        score = matrix.get_compatibility("qwen3-8b", "llama3-8b")
        assert score < 1.0  # 低于精确匹配
    
    def test_invalid(self):
        """跨家族匹配"""
        matrix = CompatibilityMatrix()
        
        # 跨家族匹配 (CROSS_FAMILY = 0.3)
        score = matrix.get_compatibility("qwen3-8b", "gpt4")
        assert score == 0.3  # CROSS_FAMILY level
