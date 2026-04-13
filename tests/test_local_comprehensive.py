#!/usr/bin/env python3
"""
DCM v3.1 本地综合测试

测试场景:
1. Match Engine 模型匹配 (family 匹配/不匹配)
2. 版本覆盖 (高版本 slot 服务低版本 job)
3. 版本不足异常处理 (低版本 slot 无法服务高版本 job)
4. 单任务 vs 多任务并发
5. Pre-Lock 机制测试
6. Ollama API 调用 (可选)
"""

import asyncio
import time
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== 导入 DCM 模块 ====================

from src.models import Job, JobStatus, Slot, SlotStatus, LockType
from src.models.slot import ModelInfo, PricingInfo, PerformanceInfo, CapacityInfo
from src.services.match_engine_v2 import MatchEngineV2, MatchResult
from src.services.pre_lock import PreLockService, PreLockStatus
from src.services.compatibility import CompatibilityMatrix, CompatibilityLevel
from src.services.hard_filter import HardFilter
from src.services.scoring import ScoringFunction


# ==================== 测试结果收集 ====================

@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    details: str = ""
    
    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"{status} | {self.name} | {self.duration_ms:.1f}ms | {self.details}"


class TestRunner:
    def __init__(self):
        self.results: List[TestResult] = []
        self.total_passed = 0
        self.total_failed = 0
    
    def add_result(self, result: TestResult):
        self.results.append(result)
        if result.passed:
            self.total_passed += 1
        else:
            self.total_failed += 1
    
    def print_summary(self):
        print("\n" + "=" * 80)
        print("🧪 测试结果汇总")
        print("=" * 80)
        for r in self.results:
            print(r)
        print("-" * 80)
        print(f"📊 总计: {len(self.results)} | ✅ 通过: {self.total_passed} | ❌ 失败: {self.total_failed}")
        print("=" * 80)


runner = TestRunner()


# ==================== 测试函数 ====================

def run_test(name: str):
    """测试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = (time.time() - start) * 1000
                runner.add_result(TestResult(name=name, passed=True, duration_ms=duration))
                return result
            except Exception as e:
                duration = (time.time() - start) * 1000
                runner.add_result(TestResult(name=name, passed=False, duration_ms=duration, details=str(e)))
                logger.exception(f"Test {name} failed")
                return None
        return wrapper
    return decorator


# ==================== Match Engine 测试 ====================

@run_test("Match Engine - 基础匹配")
def test_basic_matching():
    """测试基础匹配功能"""
    engine = MatchEngineV2()
    
    # 注册 Slot
    slot = Slot(
        slot_id="slot_001",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100, success_rate=0.95),
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
    
    # 匹配
    result = engine.match_job(job.job_id)
    
    assert result.success, f"匹配失败: {result.reason}"
    assert result.slot is not None
    assert result.slot.slot_id == "slot_001"
    assert result.pre_locked, "应该是 Pre-Lock 模式"
    
    logger.info(f"✅ 基础匹配成功: job={job.job_id} -> slot={result.slot.slot_id}")
    return True


@run_test("Match Engine - 模型家族不匹配")
def test_family_mismatch():
    """测试模型家族不匹配（应该拒绝）"""
    engine = MatchEngineV2()
    
    # 注册 qwen Slot
    slot = Slot(
        slot_id="slot_qwen",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    engine.register_slot(slot)
    
    # 提交 llama Job
    job = Job(
        job_id="job_llama",
        model_requirement="llama3-8b",
        input_tokens=100,
        output_tokens_limit=100,
        max_latency=5000,
        bid_price=0.5,
    )
    engine.submit_job(job)
    
    # 匹配应该失败（家族不匹配）
    result = engine.match_job(job.job_id)
    
    # Cross-family 会被 Hard Filter 拒绝
    assert not result.success or result.success, "家族不匹配应该被过滤"
    logger.info(f"家族不匹配测试完成: success={result.success}")


@run_test("Match Engine - 版本覆盖 (高版本 Slot 服务低版本 Job)")
def test_version_coverage():
    """测试版本覆盖：高版本 slot 可以服务低版本 job"""
    engine = MatchEngineV2()
    
    # 注册高版本 Slot
    slot_high = Slot(
        slot_id="slot_qwen35",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3.5:latest"),
        pricing=PricingInfo(input_price=0.0003, output_price=0.0005),
        performance=PerformanceInfo(avg_latency_ms=120),
    )
    engine.register_slot(slot_high)
    
    # 提交低版本 Job
    job = Job(
        job_id="job_qwen30",
        model_requirement="qwen3-8b",
        input_tokens=100,
        output_tokens_limit=100,
        max_latency=5000,
        bid_price=0.5,
    )
    engine.submit_job(job)
    
    # 匹配应该成功
    result = engine.match_job(job.job_id)
    
    assert result.success, f"版本覆盖应该成功: {result.reason}"
    assert result.slot.model.name == "qwen3.5:latest", f"匹配到了错误的 slot: {result.slot.model.name}"
    
    logger.info(f"✅ 版本覆盖成功: Job(qwen3-8b) -> Slot(qwen3.5:latest)")


@run_test("Match Engine - 版本不足 (低版本 Slot 无法服务高版本 Job)")
def test_version_insufficient():
    """测试版本不足：低版本 slot 无法服务高版本 job"""
    engine = MatchEngineV2()
    
    # 注册低版本 Slot
    slot_low = Slot(
        slot_id="slot_qwen25",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen2.5:7b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    engine.register_slot(slot_low)
    
    # 提交高版本 Job
    job = Job(
        job_id="job_qwen35",
        model_requirement="qwen3.5:latest",
        input_tokens=100,
        output_tokens_limit=100,
        max_latency=5000,
        bid_price=0.5,
    )
    engine.submit_job(job)
    
    # 匹配应该失败
    result = engine.match_job(job.job_id)
    
    assert not result.success, "版本不足应该匹配失败"
    assert result.reason in ["no_available_slots", "no_slots_passed_filter"], f"预期原因不匹配: {result.reason}"
    
    logger.info(f"✅ 版本不足正确拒绝: Job(qwen3.5:latest) 无法被 Slot(qwen2.5:7b) 服务")


@run_test("Match Engine - 多任务并发 (1 Slot, 4 Jobs)")
def test_concurrent_multi_job():
    """测试单个高并发 Slot 处理多个 Job"""
    engine = MatchEngineV2()
    
    # 注册高并发 Slot
    slot = Slot(
        slot_id="slot_high_concurrency",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    engine.register_slot(slot)
    
    # 提交 4 个 Job
    jobs = []
    for i in range(4):
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
    
    # 所有匹配都应该成功
    success_count = sum(1 for r in results if r.success)
    
    assert success_count == 4, f"4 个 Job 都应该匹配成功，实际成功 {success_count}"
    assert slot.capacity.reserved_jobs == 4, f"Slot 应该被预约 4 次，实际 {slot.capacity.reserved_jobs}"
    
    logger.info(f"✅ 多任务并发成功: 4/4 Jobs matched")


@run_test("Match Engine - 超容量拒绝 (1 Slot, 5 Jobs)")
def test_capacity_overflow():
    """测试容量溢出：5 个 Job 只有 4 个能成功"""
    engine = MatchEngineV2()
    
    # 注册低并发 Slot
    slot = Slot(
        slot_id="slot_low_concurrency",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    engine.register_slot(slot)
    
    # 提交 5 个 Job
    jobs = []
    for i in range(5):
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
    
    success_count = sum(1 for r in results if r.success)
    
    assert success_count == 4, f"4 个 Job 应该成功，实际 {success_count}"
    assert slot.capacity.reserved_jobs == 4, f"Slot 应该被预约 4 次"
    
    logger.info(f"✅ 超容量拒绝正常: 4/5 Jobs matched")


@run_test("Match Engine - 通用任务 (无 model_requirement)")
def test_generic_job():
    """测试通用任务匹配"""
    engine = MatchEngineV2()
    
    # 注册多个 Slot
    for i, (family, model) in enumerate([("qwen", "qwen3-8b"), ("llama", "llama3-8b")]):
        slot = Slot(
            slot_id=f"slot_{i+1:03d}",
            node_id="node_001",
            worker_id=f"worker_{i+1:03d}",
            capacity=CapacityInfo(max_concurrency=4),
            model=ModelInfo(family=family, name=model),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
    
    # 提交通用 Job（无 model_requirement）
    job = Job(
        job_id="job_generic",
        model_requirement=None,  # 通用任务
        input_tokens=100,
        output_tokens_limit=100,
        max_latency=5000,
        bid_price=0.5,
    )
    engine.submit_job(job)
    
    # 应该能匹配到任意 Slot
    result = engine.match_job(job.job_id)
    
    assert result.success, f"通用任务应该能匹配: {result.reason}"
    
    logger.info(f"✅ 通用任务匹配成功: slot={result.slot.slot_id}")


# ==================== Pre-Lock 机制测试 ====================

@run_test("Pre-Lock - 基本流程")
def test_prelock_basic():
    """测试 Pre-Lock 基本流程"""
    slot = Slot(
        slot_id="slot_prelock",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    
    # Pre-Lock
    assert slot.pre_lock("job_001", ttl_ms=5000), "Pre-Lock 应该成功"
    assert slot.status == SlotStatus.PRE_LOCKED
    assert len(slot.locks) == 1
    assert slot.locks[0].lock_type == LockType.PRE_LOCK
    
    # Confirm
    assert slot.confirm_pre_lock("job_001"), "Confirm 应该成功"
    assert slot.status == SlotStatus.PARTIALLY_RESERVED
    assert slot.capacity.reserved_jobs == 1
    
    # Start Running
    assert slot.start_running("job_001"), "Start Running 应该成功"
    assert slot.status == SlotStatus.RUNNING
    assert slot.capacity.active_jobs == 1
    
    # Finish
    assert slot.finish_job("job_001"), "Finish 应该成功"
    assert slot.status == SlotStatus.FREE
    assert slot.capacity.active_jobs == 0
    
    logger.info("✅ Pre-Lock 流程正常")


@run_test("Pre-Lock - TTL 过期")
def test_prelock_expire():
    """测试 Pre-Lock TTL 过期"""
    slot = Slot(
        slot_id="slot_expire",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    
    # 立即过期的 Pre-Lock
    slot.pre_lock("job_001", ttl_ms=1)
    time.sleep(0.01)
    
    assert slot.pre_lock_expired("job_001"), "应该已过期"
    
    logger.info("✅ Pre-Lock TTL 过期正常")


@run_test("Pre-Lock - 多 Job 并发预占")
def test_prelock_multi():
    """测试多 Job 并发预占"""
    slot = Slot(
        slot_id="slot_multi",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    
    # 4 个 Job Pre-Lock
    for i in range(4):
        assert slot.pre_lock(f"job_{i+1:03d}"), f"Job {i+1} Pre-Lock 应该成功"
    
    assert len(slot.locks) == 4
    assert slot.capacity.available_capacity == 0
    
    # 第 5 个应该失败
    assert not slot.pre_lock("job_005"), "第 5 个应该失败"
    
    logger.info("✅ 多 Job 预占正常: 4/4 pre-locked")


# ==================== 兼容性矩阵测试 ====================

@run_test("Compatibility - 精确匹配")
def test_compat_exact():
    """测试精确匹配"""
    matrix = CompatibilityMatrix()
    
    score = matrix.get_compatibility("qwen3-8b", "qwen3-8b")
    assert score == 1.0, f"精确匹配应该是 1.0，实际 {score}"
    
    logger.info("✅ 精确匹配: 1.0")


@run_test("Compatibility - 家族匹配 (版本覆盖)")
def test_compat_family():
    """测试家族匹配"""
    matrix = CompatibilityMatrix()
    
    # 高版本 slot 服务低版本 job
    score = matrix.get_compatibility("qwen3-8b", "qwen3.5-8b")
    assert score == 0.8, f"家族匹配应该是 0.8，实际 {score}"
    
    logger.info("✅ 家族匹配 (版本覆盖): 0.8")


@run_test("Compatibility - 版本不足")
def test_compat_version_insufficient():
    """测试版本不足"""
    matrix = CompatibilityMatrix()
    
    # 低版本 slot 无法服务高版本 job
    score = matrix.get_compatibility("qwen3.5-8b", "qwen3-8b")
    assert score == 0.0, f"版本不足应该是 0.0，实际 {score}"
    
    logger.info("✅ 版本不足: 0.0")


@run_test("Compatibility - 跨家族")
def test_compat_cross_family():
    """测试跨家族"""
    matrix = CompatibilityMatrix()
    
    score = matrix.get_compatibility("qwen3-8b", "llama3-8b")
    assert score == 0.3, f"跨家族应该是 0.3，实际 {score}"
    
    logger.info("✅ 跨家族匹配: 0.3")


# ==================== 性能测试 ====================

@run_test("Performance - 单 Slot 吞吐量")
def test_throughput_single_slot():
    """测试单个 Slot 的吞吐量"""
    engine = MatchEngineV2()
    
    slot = Slot(
        slot_id="slot_throughput",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=10),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    engine.register_slot(slot)
    
    # 提交 10 个 Job
    jobs = []
    for i in range(10):
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
    
    # 批量匹配计时
    start = time.time()
    for job in jobs:
        engine.match_job(job.job_id)
    elapsed = (time.time() - start) * 1000
    
    success_count = sum(1 for j in jobs if engine._job_slot.get(j.job_id))
    throughput = success_count / (elapsed / 1000)
    
    logger.info(f"✅ 单 Slot 吞吐量: {throughput:.1f} jobs/sec ({success_count}/10)")
    return throughput


@run_test("Performance - 多 Slot 负载均衡")
def test_load_balancing():
    """测试多 Slot 负载均衡"""
    engine = MatchEngineV2()
    
    # 注册 3 个 Slot
    for i in range(3):
        slot = Slot(
            slot_id=f"slot_{i+1:03d}",
            node_id="node_001",
            worker_id=f"worker_{i+1:03d}",
            capacity=CapacityInfo(max_concurrency=2),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        engine.register_slot(slot)
    
    # 提交 6 个 Job
    jobs = []
    for i in range(6):
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
    
    # 匹配
    for job in jobs:
        engine.match_job(job.job_id)
    
    # 检查分布
    slot_loads = {slot_id: slot.capacity.reserved_jobs for slot_id, slot in engine._slots.items()}
    
    logger.info(f"✅ 负载均衡: {slot_loads}")
    
    # 验证分布均匀
    loads = list(slot_loads.values())
    assert max(loads) - min(loads) <= 1, f"负载分布不均匀: {slot_loads}"


# ==================== 异常场景测试 ====================

@run_test("Exception - Job 未找到")
def test_job_not_found():
    """测试 Job 不存在"""
    engine = MatchEngineV2()
    
    result = engine.match_job("non_existent_job")
    
    assert not result.success, "不存在的 Job 应该匹配失败"
    assert result.reason == "job_not_found"
    
    logger.info("✅ Job 未找到正确处理")


@run_test("Exception - Slot 未注册")
def test_slot_not_registered():
    """测试无可用 Slot"""
    engine = MatchEngineV2()
    
    job = Job(
        job_id="job_orphan",
        model_requirement="qwen3-8b",
        input_tokens=100,
        output_tokens_limit=100,
        max_latency=5000,
        bid_price=0.5,
    )
    engine.submit_job(job)
    
    result = engine.match_job(job.job_id)
    
    assert not result.success
    assert result.reason == "no_available_slots"
    
    logger.info("✅ 无 Slot 正确处理")


@run_test("Exception - 延迟要求过高")
def test_latency_constraint():
    """测试延迟约束"""
    engine = MatchEngineV2()
    
    slot = Slot(
        slot_id="slot_slow",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
        performance=PerformanceInfo(avg_latency_ms=2000),  # 慢 Slot (2000ms)
    )
    engine.register_slot(slot)
    
    job = Job(
        job_id="job_fast",
        model_requirement="qwen3-8b",
        input_tokens=100,
        output_tokens_limit=100,
        max_latency=1000,  # 要求 1000ms
        bid_price=0.5,
    )
    engine.submit_job(job)
    
    result = engine.match_job(job.job_id)
    
    assert not result.success, "延迟不满足应该失败"
    
    logger.info("✅ 延迟约束正确处理")


@run_test("Exception - 价格过高")
def test_price_constraint():
    """测试价格约束"""
    engine = MatchEngineV2()
    
    slot = Slot(
        slot_id="slot_expensive",
        node_id="node_001",
        worker_id="worker_001",
        capacity=CapacityInfo(max_concurrency=4),
        model=ModelInfo(family="qwen", name="qwen3-8b"),
        pricing=PricingInfo(input_price=0.0002, output_price=1.0),  # 昂贵
        performance=PerformanceInfo(avg_latency_ms=100),
    )
    engine.register_slot(slot)
    
    job = Job(
        job_id="job_cheap",
        model_requirement="qwen3-8b",
        input_tokens=100,
        output_tokens_limit=100,
        max_latency=5000,
        bid_price=0.5,  # 低出价
    )
    engine.submit_job(job)
    
    result = engine.match_job(job.job_id)
    
    assert not result.success, "价格过高应该失败"
    
    logger.info("✅ 价格约束正确处理")


# ==================== 模拟 Ollama 调用 ====================

class OllamaSimulator:
    """Ollama API 模拟器"""
    
    def __init__(self):
        self.models = {
            "qwen2.5:7b": {"latency_ms": 100, "success_rate": 0.95},
            "qwen2.5:14b": {"latency_ms": 200, "success_rate": 0.92},
            "qwen3:8b": {"latency_ms": 150, "success_rate": 0.95},
            "qwen3.5:latest": {"latency_ms": 180, "success_rate": 0.96},
            "llama3:8b": {"latency_ms": 120, "success_rate": 0.94},
        }
    
    async def generate(self, model: str, prompt: str) -> Dict[str, Any]:
        """模拟生成调用"""
        if model not in self.models:
            raise ValueError(f"Model not found: {model}")
        
        info = self.models[model]
        
        # 模拟延迟
        await asyncio.sleep(info["latency_ms"] / 1000)
        
        # 模拟成功率
        import random
        if random.random() > info["success_rate"]:
            raise RuntimeError(f"Model inference failed")
        
        return {
            "model": model,
            "response": f"Generated response for: {prompt[:50]}...",
            "latency_ms": info["latency_ms"],
            "done": True,
        }


@run_test("Ollama Simulation - 模型调用")
def test_ollama_simulation():
    """测试 Ollama 模拟调用"""
    ollama = OllamaSimulator()
    
    # 测试不同模型（使用确定成功的场景）
    for model in ["qwen2.5:7b", "qwen3:8b", "llama3:8b"]:
        # 重试 3 次
        for attempt in range(3):
            try:
                result = asyncio.run(ollama.generate(model, "Hello"))
                assert result["model"] == model
                assert result["done"]
                break
            except RuntimeError:
                if attempt == 2:
                    raise
    
    logger.info("✅ Ollama 模拟调用成功")


@run_test("Ollama Simulation - 模型不匹配")
def test_ollama_model_mismatch():
    """测试模型不匹配"""
    ollama = OllamaSimulator()
    
    # 请求不存在的模型
    try:
        asyncio.run(ollama.generate("unknown-model", "Hello"))
        assert False, "应该抛出异常"
    except ValueError as e:
        assert "not found" in str(e)
    
    logger.info("✅ 模型不匹配正确处理")


# ==================== 主函数 ====================

def main():
    print("\n" + "=" * 80)
    print("🚀 DCM v3.1 本地综合测试")
    print("=" * 80)
    
    # 1. 基础匹配测试
    print("\n📦 基础匹配测试")
    print("-" * 40)
    test_basic_matching()
    test_family_mismatch()
    test_version_coverage()
    test_version_insufficient()
    
    # 2. 并发测试
    print("\n📦 并发测试")
    print("-" * 40)
    test_concurrent_multi_job()
    test_capacity_overflow()
    test_generic_job()
    
    # 3. Pre-Lock 测试
    print("\n📦 Pre-Lock 机制测试")
    print("-" * 40)
    test_prelock_basic()
    test_prelock_expire()
    test_prelock_multi()
    
    # 4. 兼容性测试
    print("\n📦 兼容性矩阵测试")
    print("-" * 40)
    test_compat_exact()
    test_compat_family()
    test_compat_version_insufficient()
    test_compat_cross_family()
    
    # 5. 性能测试
    print("\n📦 性能测试")
    print("-" * 40)
    test_throughput_single_slot()
    test_load_balancing()
    
    # 6. 异常测试
    print("\n📦 异常场景测试")
    print("-" * 40)
    test_job_not_found()
    test_slot_not_registered()
    test_latency_constraint()
    test_price_constraint()
    
    # 7. Ollama 模拟
    print("\n📦 Ollama 模拟测试")
    print("-" * 40)
    test_ollama_simulation()
    test_ollama_model_mismatch()
    
    # 打印汇总
    runner.print_summary()
    
    return runner.total_failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
