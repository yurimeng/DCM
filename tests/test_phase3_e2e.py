"""
Phase 3 E2E Tests - DCM v3.1
测试 Pre-Lock 机制和 Multi-Job 并发
"""

import pytest
from datetime import datetime

from src.models import Job, JobStatus, Slot, SlotStatus, LockType, JobSet
from src.models.slot import ModelInfo, PricingInfo, PerformanceInfo, CapacityInfo
from src.services.match_engine_v2 import MatchEngineV2, MatchResult, DispatchResult
from src.services.pre_lock import PreLockService, PreLockStatus, PreLockResult


@pytest.fixture
def engine():
    """创建 Match Engine"""
    return MatchEngineV2()


class TestPreLockMechanism:
    """Pre-Lock 机制测试"""
    
    def test_slot_pre_lock_request(self):
        """测试 Slot Pre-Lock 请求"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Pre-Lock 请求
        assert slot.pre_lock("job_001", ttl_ms=5000) == True
        assert slot.status == SlotStatus.PRE_LOCKED
        assert len(slot.locks) == 1
        assert slot.locks[0].lock_type == LockType.PRE_LOCK
        
        # 同一 Job 不能重复 Pre-Lock
        assert slot.pre_lock("job_001", ttl_ms=5000) == False
    
    def test_slot_pre_lock_confirm(self):
        """测试 Pre-Lock 确认"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Pre-Lock 并确认
        slot.pre_lock("job_001", ttl_ms=5000)
        assert slot.confirm_pre_lock("job_001") == True
        
        # 状态更新
        assert len(slot.locks) == 1
        assert slot.locks[0].lock_type == LockType.HARD_LOCK
        assert "job_001" in slot.job_sets.reserved
        assert slot.capacity.reserved_jobs == 1
        assert slot.status == SlotStatus.PARTIALLY_RESERVED
    
    def test_slot_pre_lock_expire(self):
        """测试 Pre-Lock 过期"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # 创建立即过期的 Pre-Lock
        slot.pre_lock("job_001", ttl_ms=0)  # 0ms TTL
        import time
        time.sleep(0.01)  # 等待过期
        
        assert slot.pre_lock_expired("job_001") == True
    
    def test_slot_multi_job_pre_lock(self):
        """测试 Slot 多 Job Pre-Lock"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Pre-Lock 3 个 Job
        assert slot.pre_lock("job_001") == True
        assert slot.pre_lock("job_002") == True
        assert slot.pre_lock("job_003") == True
        
        assert len(slot.locks) == 3
        assert slot.capacity.pre_locked_jobs == 3
        assert slot.capacity.available_capacity == 1  # 4 - 3 = 1
        
        # 第 4 个成功
        assert slot.pre_lock("job_004") == True
        assert slot.capacity.available_capacity == 0
        
        # 第 5 个失败（容量已满）
        assert slot.pre_lock("job_005") == False
    
    def test_slot_lock_release(self):
        """测试 Lock 释放"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Pre-Lock 并确认
        slot.pre_lock("job_001")
        slot.confirm_pre_lock("job_001")
        
        assert slot.capacity.reserved_jobs == 1
        
        # 释放
        assert slot.release_lock("job_001") == True
        assert len(slot.locks) == 0
        assert slot.capacity.reserved_jobs == 0
        assert slot.status == SlotStatus.FREE


class TestPreLockService:
    """Pre-Lock 服务测试"""
    
    def test_pre_lock_service_request(self):
        """测试 Pre-Lock 服务请求"""
        service = PreLockService(default_ttl_ms=5000)
        
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        result = service.request_pre_lock("job_001", slot)
        
        assert result.success == True
        assert result.status == PreLockStatus.PENDING
        assert result.expires_at is not None
    
    def test_pre_lock_service_ack(self):
        """测试 Pre-Lock Ack"""
        service = PreLockService(default_ttl_ms=5000)
        
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Request -> Ack
        service.request_pre_lock("job_001", slot)
        ack_result = service.receive_ack("job_001", slot)
        
        assert ack_result.success == True
        assert ack_result.status == PreLockStatus.LOCKED
        assert "job_001" in slot.job_sets.reserved
    
    def test_pre_lock_service_expire(self):
        """测试 Pre-Lock 过期"""
        service = PreLockService(default_ttl_ms=1)  # 1ms TTL
        
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # Request
        service.request_pre_lock("job_001", slot)
        
        # Wait for expiry
        import time
        time.sleep(0.01)
        
        # Ack should fail due to expiry
        ack_result = service.receive_ack("job_001", slot)
        
        assert ack_result.success == False
        assert ack_result.status == PreLockStatus.EXPIRED


class TestMatchEnginePreLock:
    """Match Engine Pre-Lock 测试"""
    
    def test_e2e_match_with_pre_lock(self, engine):
        """E2E: 匹配 + Pre-Lock"""
        # 注册 Slot
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        # 提交 Job
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job)
        
        # 匹配（包含 Pre-Lock）
        result = engine.match_job(job.job_id)
        
        assert result.success == True
        assert result.pre_locked == True
        assert result.slot is not None
        assert result.job is not None
        assert result.pre_lock_expires_at is not None
        
        # 验证 Slot 状态
        assert slot.status == SlotStatus.PARTIALLY_RESERVED
        assert "job_001" in slot.job_sets.reserved
        assert slot.capacity.reserved_jobs == 1
    
    def test_e2e_multi_job_match(self, engine):
        """E2E: 多 Job 并发匹配"""
        # 注册高并发 Slot
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        # 提交 3 个 Job
        jobs = []
        for i in range(3):
            job = Job(
                job_id=f"job_{i+1:03d}",
                model_requirement="qwen3-8b",
                input_tokens=100,
                output_tokens_limit=100,
                max_latency=5000,
                bid_price=0.5,
            )
            engine.submit_job(job)
            jobs.append(job)
        
        # 依次匹配
        results = []
        for job in jobs:
            result = engine.match_job(job.job_id)
            results.append(result)
        
        # 所有匹配成功
        assert all(r.success for r in results)
        assert slot.capacity.reserved_jobs == 3
        assert slot.capacity.available_capacity == 1
    
    def test_e2e_pre_lock_slot_full(self, engine):
        """E2E: Slot 满后无法匹配"""
        # 注册低并发 Slot
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1),  # 只有 1 个并发
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        # 注册第二个 Slot
        slot2 = Slot(
            slot_id="slot_002",
            node_id="node_002",
            worker_id="worker_002",
            capacity=CapacityInfo(max_concurrency=1),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot2)
        
        # 匹配第一个 Job 到 slot_001
        job1 = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job1)
        result1 = engine.match_job(job1.job_id)
        
        assert result1.success == True
        assert result1.slot.slot_id == "slot_001"
        
        # 第二个 Job 应该匹配到 slot_002
        job2 = Job(
            job_id="job_002",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job2)
        result2 = engine.match_job(job2.job_id)
        
        assert result2.success == True
        assert result2.slot.slot_id == "slot_002"
    
    def test_e2e_version_coverage_with_pre_lock(self, engine):
        """E2E: 版本覆盖 + Pre-Lock"""
        # 注册高版本 Slot
        slot = Slot(
            slot_id="slot_high",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3.5:latest"),  # 高版本
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        # 低版本 Job
        job = Job(
            job_id="job_low",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job)
        
        # 应该匹配成功（版本覆盖：高版本 slot 可服务低版本 job）
        result = engine.match_job(job.job_id)
        
        assert result.success == True
        assert result.slot.model.name == "qwen3.5:latest"
    
    def test_e2e_version_insufficient_with_pre_lock(self, engine):
        """E2E: 版本不足 + Pre-Lock"""
        # 注册更低版本 Slot
        slot = Slot(
            slot_id="slot_low",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen2.5:7b"),  # 太低版本
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        # 高版本 Job
        job = Job(
            job_id="job_high",
            model_requirement="qwen3.5:latest",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job)
        
        # 应该匹配失败（版本不足）
        result = engine.match_job(job.job_id)
        
        assert result.success == False


class TestDispatchFlow:
    """分发流程测试"""
    
    def test_e2e_dispatch_flow(self, engine):
        """E2E: 完整分发流程"""
        # 注册 Slot
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        # 提交并匹配 Job
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job)
        
        result = engine.match_job(job.job_id)
        assert result.success == True
        
        # 分发
        dispatch_result = engine.dispatch_job(job.job_id)
        assert dispatch_result.success == True
        assert dispatch_result.worker_id == "worker_001"
        
        # 开始执行
        start_result = engine.start_job_execution(job.job_id)
        assert start_result == True
        assert slot.status == SlotStatus.RUNNING
        assert "job_001" in slot.job_sets.running
        assert slot.capacity.active_jobs == 1
        
        # 完成
        complete_result = engine.complete_job(job.job_id)
        assert complete_result == True
        assert slot.status == SlotStatus.FREE
        assert slot.capacity.active_jobs == 0


class TestSlotLifecycle:
    """Slot 生命周期测试"""
    
    def test_slot_status_transitions(self):
        """测试 Slot 状态转换"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # FREE
        assert slot.status == SlotStatus.FREE
        assert slot.is_available() == True
        
        # PRE_LOCKED
        slot.pre_lock("job_001")
        assert slot.status == SlotStatus.PRE_LOCKED
        
        # PARTIALLY_RESERVED
        slot.confirm_pre_lock("job_001")
        assert slot.status == SlotStatus.PARTIALLY_RESERVED
        
        # RUNNING
        slot.start_running("job_001")
        assert slot.status == SlotStatus.RUNNING
        
        # FREE (after release)
        slot.finish_job("job_001")
        assert slot.status == SlotStatus.FREE
    
    def test_slot_capacity_updates(self):
        """测试 Slot 容量更新"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        assert slot.capacity.available_capacity == 4
        
        # 3 个 Job Pre-Lock
        for i in range(3):
            slot.pre_lock(f"job_{i+1:03d}")
            slot.confirm_pre_lock(f"job_{i+1:03d}")
        
        assert slot.capacity.reserved_jobs == 3
        assert slot.capacity.available_capacity == 1
        assert slot.status == SlotStatus.PARTIALLY_RESERVED
        
        # 第 4 个 Job 开始运行
        slot.start_running("job_001")
        assert slot.capacity.reserved_jobs == 2
        assert slot.capacity.active_jobs == 1
        assert slot.capacity.available_capacity == 1


class TestJobStatusTransitions:
    """Job 状态转换测试"""
    
    def test_job_status_flow(self):
        """测试 Job 状态流转"""
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        # PENDING
        assert job.status == JobStatus.PENDING
        
        # MATCHED
        job.status = JobStatus.MATCHED
        job.matched_at = datetime.utcnow()
        
        # RESERVED
        job.status = JobStatus.RESERVED
        job.reserved_at = datetime.utcnow()
        
        # DISPATCHED
        job.status = JobStatus.DISPATCHED
        job.dispatched_at = datetime.utcnow()
        
        # RUNNING
        job.status = JobStatus.RUNNING
        
        # COMPLETED
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        assert job.is_terminal() == True


class TestStatsTracking:
    """统计追踪测试"""
    
    def test_e2e_stats_tracking(self, engine):
        """E2E: 统计追踪"""
        # 注册 5 个 Slot
        for i in range(5):
            slot = Slot(
                slot_id=f"slot_{i+1:03d}",
                node_id="node_001",
                worker_id=f"worker_{i+1:03d}",
                capacity=CapacityInfo(max_concurrency=4),
                model=ModelInfo(family="qwen", name="qwen3-8b"),
                pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
                performance=PerformanceInfo(avg_latency_ms=100),
            )
            engine.register_slot(slot)
        
        # 提交 3 个 Job
        for i in range(3):
            job = Job(
                job_id=f"job_{i+1:03d}",
                model_requirement="qwen3-8b",
                input_tokens=100,
                output_tokens_limit=100,
                max_latency=5000,
                bid_price=0.5,
            )
            engine.submit_job(job)
        
        # 匹配 2 个
        for i in range(2):
            engine.match_job(f"job_{i+1:03d}")
        
        stats = engine.get_stats()
        
        assert stats["total_slots"] == 5
        # DCM v3.1: Slots with capacity are still "available"
        # Since each slot has max_concurrency=4 and only 1 reserved,
        # all 5 slots still have capacity
        assert stats["available_slots"] == 5  # All slots have capacity
        assert stats["pending_jobs"] == 1
        assert stats["active_matches"] == 2


class TestEdgeCases:
    """边界情况测试"""
    
    def test_no_available_slots(self, engine):
        """无可用 Slot"""
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job)
        
        result = engine.match_job(job.job_id)
        
        assert result.success == False
        assert result.reason == "no_available_slots"
    
    def test_job_not_found(self, engine):
        """Job 不存在"""
        result = engine.match_job("non_existent_job")
        
        assert result.success == False
        assert result.reason == "job_not_found"
    
    def test_slot_full_no_match(self, engine):
        """Slot 满后无法匹配"""
        # 注册只有 1 个容量的 Slot
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        # 匹配 1 个 Job
        job1 = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job1)
        result1 = engine.match_job(job1.job_id)
        assert result1.success == True
        
        # 尝试匹配第二个（应该失败或匹配到其他 Slot）
        job2 = Job(
            job_id="job_002",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job2)
        result2 = engine.match_job(job2.job_id)
        
        # 由于只有一个 Slot，应该失败
        assert result2.success == False
    
    def test_cancel_releases_pre_lock(self, engine):
        """取消 Job 释放 Pre-Lock"""
        slot = Slot(
            slot_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        engine.submit_job(job)
        
        result = engine.match_job(job.job_id)
        assert result.success == True
        
        # 取消
        cancelled_job = engine.cancel_job(job.job_id)
        assert cancelled_job is not None
        
        # Slot 应该释放
        assert slot.status == SlotStatus.FREE
        assert slot.capacity.reserved_jobs == 0
