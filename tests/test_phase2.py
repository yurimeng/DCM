"""
Phase 2 Tests - DCM v3.1
测试核心服务
"""

import pytest
from datetime import datetime, timedelta

from src.models import Job, JobStatus, Slot, SlotStatus, LockType, JobSet
from src.models.cluster import ModelInfo, PricingInfo, PerformanceInfo, CapacityInfo
from src.services.order_book import OrderBook
from src.services.hard_filter import HardFilter, create_default_filter
from src.services.scoring import ScoringFunction, scoring_function, ScoreBreakdown
from src.services.pre_lock import PreLockService, PreLockStatus, pre_lock_service
from src.services.node_status_store import node_status_store


def setup_node_status(node_id: str, available_concurrency: int = 4, available_queue_tokens: int = 3000):
    """Setup mock Node status for tests"""
    node_status_store.update(node_id, {
        "timestamp": 1713000000000,
        "status": {"vram_used_gb": 18, "vram_total_gb": 48},
        "capacity": {"max_concurrency_available": available_concurrency},
        "load": {
            "active_jobs": 0,
            "available_token_capacity": available_queue_tokens
        }
    })


class TestOrderBook:
    """Order Book 测试"""
    
    def test_add_job(self):
        """添加 Job"""
        book = OrderBook()
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        book.add_job(job)
        
        assert len(book.get_all_jobs()) == 1
    
    def test_add_slot(self):
        """添加 Slot"""
        book = OrderBook()
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        book.add_slot(slot)
        
        assert len(book.get_slots()) == 1
    
    def test_get_slots_by_family(self):
        """按家族获取 Slots"""
        book = OrderBook()
        
        book.add_slot(Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        ))
        
        book.add_slot(Slot(
            cluster_id="slot_002",
            node_id="node_001",
            worker_id="worker_002",
            model=ModelInfo(family="llama", name="llama3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        ))
        
        qwen_slots = book.get_slots("qwen")
        assert len(qwen_slots) == 1
        assert qwen_slots[0].model.family == "qwen"
    
    def test_remove_job(self):
        """移除 Job"""
        book = OrderBook()
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        book.add_job(job)
        removed = book.remove_job("job_001")
        
        assert removed is not None
        assert len(book.get_all_jobs()) == 0
    
    def test_remove_slot(self):
        """移除 Slot"""
        book = OrderBook()
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        book.add_slot(slot)
        removed = book.remove_slot("slot_001")
        
        assert removed is not None
        assert len(book.get_slots()) == 0


class TestHardFilter:
    """Hard Filter 测试"""
    
    def test_basic_filter(self):
        """基础过滤"""
        hf = HardFilter()
        
        # Setup mock Node status
        setup_node_status("slot_001", available_concurrency=4, available_queue_tokens=3000)
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        passed, reason = hf.filter(slot, job)
        
        assert passed == True
        assert reason is None
    
    def test_model_incompatible(self):
        """模型完全不兼容（家族不同但可能被接受）"""
        hf = HardFilter()
        
        setup_node_status("slot_001")
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # 跨家族模型
        job = Job(
            job_id="job_001",
            model_requirement="gpt4",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        passed, reason = hf.filter(slot, job)
        
        # Cross-family 应该失败
        assert passed == False
        assert reason == "model_not_supported"
    
    def test_latency_too_high(self):
        """延迟过高"""
        hf = HardFilter()
        
        # Setup mock Node status
        setup_node_status("slot_002")
        
        # 使用 slot 延迟超过 job 的 max_latency
        slot_very_slow = Slot(
            cluster_id="slot_002",
            node_id="node_001",
            worker_id="worker_002",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=1500),  # 1500ms 延迟
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=1000,  # 1000ms
            bid_price=0.5,
        )
        
        passed, reason = hf.filter(slot_very_slow, job)
        
        # slot 延迟 1500ms > job 要求 1000ms，应该失败
        assert passed == False
        assert reason == "latency_too_high"
    
    def test_price_too_high(self):
        """价格过高"""
        hf = HardFilter()
        
        setup_node_status("slot_001")
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=1.0),  # 输出价格太高
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        passed, reason = hf.filter(slot, job)
        
        assert passed == False
        assert reason == "output_price_too_high"
    
    def test_filter_many(self):
        """批量过滤"""
        hf = HardFilter()
        
        # Setup mock Node status for all slots
        for i in range(5):
            setup_node_status(f"slot_{i:03d}")
        
        slots = [
            Slot(
                cluster_id=f"slot_{i:03d}",
                node_id="node_001",
                worker_id=f"worker_{i:03d}",
                model=ModelInfo(family="qwen", name="qwen3-8b"),
                pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
                performance=PerformanceInfo(avg_latency_ms=100),
            )
            for i in range(5)
        ]
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        filtered = hf.filter_many(slots, job)
        
        assert len(filtered) == 5


class TestScoringFunction:
    """Scoring 函数测试"""
    
    def test_price_score(self):
        """测试价格评分"""
        sf = ScoringFunction()
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1, current_load=0),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        breakdown = sf.get_breakdown(slot, job)
        
        assert breakdown.price_score > 0
        assert breakdown.total_score > 0
    
    def test_latency_score(self):
        """测试延迟评分"""
        sf = ScoringFunction()
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1, current_load=0),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=50),  # 更快
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        breakdown = sf.get_breakdown(slot, job)
        
        assert breakdown.latency_score > 0.9  # 延迟很低
    
    def test_load_score(self):
        """测试负载评分"""
        sf = ScoringFunction()
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4, current_load=1),  # 有负载
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        breakdown = sf.get_breakdown(slot, job)
        
        assert breakdown.load_score > 0  # 负载评分
    
    def test_total_score_calculation(self):
        """测试总分计算"""
        sf = ScoringFunction()
        
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1, current_load=0),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        score = sf.calculate(slot, job)
        
        assert 0 <= score <= 1
    
    def test_rank_slots(self):
        """测试 Slot 排序"""
        sf = ScoringFunction()
        
        # 两个不同的 Slot
        slot1 = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1, current_load=0),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        slot2 = Slot(
            cluster_id="slot_002",
            node_id="node_002",
            worker_id="worker_002",
            capacity=CapacityInfo(max_concurrency=1, current_load=0),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0003, output_price=0.0005),
            performance=PerformanceInfo(avg_latency_ms=50),
        )
        
        job = Job(
            job_id="job_001",
            model_requirement="qwen3-8b",
            input_tokens=100,
            output_tokens_limit=100,
            max_latency=5000,
            bid_price=0.5,
        )
        
        ranked = sf.rank_slots([slot1, slot2], job)
        
        assert len(ranked) == 2
        print(f"Slot1 score: {ranked[0][1]:.3f}, Slot2 score: {ranked[1][1]:.3f}")


class TestSlotLifecycle:
    """Slot 生命周期测试"""
    
    def test_reserve_free_to_reserved(self):
        """FREE → RESERVED 转换"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=4),  # 使用更高的并发
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # 使用新的 Pre-Lock 机制
        assert slot.pre_lock("job_001") == True
        assert slot.status == SlotStatus.PRE_LOCKED
        
        assert slot.confirm_pre_lock("job_001") == True
        assert slot.status == SlotStatus.PARTIALLY_RESERVED
    
    def test_start_running(self):
        """开始运行"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        slot.pre_lock("job_001")
        slot.confirm_pre_lock("job_001")
        assert slot.start_running("job_001") == True
        
        assert slot.status == SlotStatus.RUNNING
        assert "job_001" in slot.job_sets.running
        assert slot.capacity.active_jobs == 1
    
    def test_release(self):
        """释放"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # 完整流程
        slot.pre_lock("job_001")
        slot.confirm_pre_lock("job_001")
        slot.start_running("job_001")
        slot.finish_job("job_001")
        
        assert slot.status == SlotStatus.FREE
        assert len(slot.locks) == 0
    
    def test_reset_to_free(self):
        """重置到 FREE"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        slot.pre_lock("job_001")
        slot.reset_to_free()
        
        assert slot.status == SlotStatus.FREE
        assert len(slot.locks) == 0
    
    def test_concurrent_capacity(self):
        """测试容量限制"""
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            capacity=CapacityInfo(max_concurrency=1),
            model=ModelInfo(family="qwen", name="qwen3-8b"),
            pricing=PricingInfo(input_price=0.0002, output_price=0.0004),
            performance=PerformanceInfo(avg_latency_ms=100),
        )
        
        # 可以预约一次
        assert slot.pre_lock("job_001") == True
        assert slot.confirm_pre_lock("job_001") == True
        
        # 第二次预约失败
        assert slot.pre_lock("job_002") == False


class TestPreLockService:
    """Pre-Lock 服务测试"""
    
    def test_request_pre_lock(self):
        """请求 Pre-Lock"""
        service = PreLockService(default_ttl_ms=5000)
        
        slot = Slot(
            cluster_id="slot_001",
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
    
    def test_receive_ack(self):
        """接收 Ack"""
        service = PreLockService(default_ttl_ms=5000)
        
        slot = Slot(
            cluster_id="slot_001",
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


class TestPhase2Integration:
    """Phase 2 集成测试"""
    
    def test_full_match_engine_flow(self):
        """完整 Match Engine 流程"""
        from src.services.match_engine_v2 import MatchEngineV2
        from src.models.node import Node, NodeState
        
        engine = MatchEngineV2()
        
        # 注册 Node (DCM v3.2)
        node = Node(
            node_id="node_001",
            user_id="user_001",
            location={"region": "us-west", "hostname": "node-001"},
            hardware={"gpu_type": "RTX4090", "gpu_count": 1, "vram_per_gpu_gb": 24},
            runtime={"type": "ollama", "loaded_models": ["qwen3-8b"]},
            pricing={"ask_price_usdc_per_mtoken": 0.5},
        )
        engine.register_node(node)
        
        # 设置 Node 状态 (DCM v3.2 使用 node_id)
        setup_node_status("node_001", available_concurrency=4, available_queue_tokens=3000)
        
        # 注册 Cluster (关联到 Node)
        slot = Slot(
            cluster_id="slot_001",
            node_id="node_001",
            worker_id="worker_001",
            node_ids=["node_001"],  # DCM v3.2
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
        
        # 匹配
        result = engine.match_job(job.job_id)
        
        assert result.success == True
        assert result.cluster is not None
        
        # 分发
        dispatch_result = engine.dispatch_job(job.job_id)
        assert dispatch_result.success == True
        
        # 开始执行
        start_result = engine.start_job_execution(job.job_id)
        assert start_result == True
        
        # 完成
        complete_result = engine.complete_job(job.job_id)
        assert complete_result == True
        
        # 验证 Slot 状态
        assert slot.status == SlotStatus.FREE
