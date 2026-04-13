"""
F10: Scaler - ScalerService 测试
"""

import pytest
import asyncio
from datetime import datetime

import sys
sys.path.insert(0, '.')

from src.core.cluster import (
    ScalerService,
    ScalingConfig,
    ScalingMetrics,
    ScalingThresholds,
    ScalingAction,
)


@pytest.fixture
def scaler_service():
    """创建 Scaler 服务实例"""
    config = ScalingConfig(
        enabled=True,
        min_workers=0,
        max_workers=10,
        check_interval_sec=1,
        thresholds=ScalingThresholds(
            cpu_scale_up=80.0,
            cpu_scale_down=20.0,
            queue_scale_up=100,
            worker_idle_sec=300
        )
    )
    return ScalerService(config)


@pytest.fixture
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestScalerService:
    """ScalerService 测试"""
    
    @pytest.mark.asyncio
    async def test_init(self, scaler_service):
        """测试初始化"""
        assert scaler_service is not None
        assert scaler_service.config is not None
        assert len(scaler_service._workers) == 0
    
    @pytest.mark.asyncio
    async def test_scale_up(self, scaler_service):
        """测试扩容"""
        workers = await scaler_service.scale_up(3)
        
        assert len(workers) == 3
        assert len(scaler_service._workers) == 3
        assert scaler_service.get_status()["current_workers"] == 3
    
    @pytest.mark.asyncio
    async def test_scale_down(self, scaler_service):
        """测试缩容"""
        # 先扩容
        await scaler_service.scale_up(5)
        
        # 模拟 Worker 空闲 (更新 last_heartbeat)
        from datetime import timedelta
        for worker in scaler_service._workers.values():
            worker.last_heartbeat = datetime.utcnow() - timedelta(seconds=400)  # > 300s idle
        
        # 再缩容
        removed = await scaler_service.scale_down(2)
        
        assert len(removed) == 2
        assert len(scaler_service._workers) == 3
    
    @pytest.mark.asyncio
    async def test_scale_up_max_limit(self, scaler_service):
        """测试扩容上限"""
        # 尝试扩容超过最大值
        workers = await scaler_service.scale_up(15)
        
        # 应该只扩容到 max_workers
        assert len(workers) == 10
        assert len(scaler_service._workers) == 10
    
    @pytest.mark.asyncio
    async def test_scale_down_min_limit(self, scaler_service):
        """测试缩容下限"""
        scaler_service.config.min_workers = 2
        
        # 先扩容到 5
        await scaler_service.scale_up(5)
        
        # 尝试缩容到 0
        removed = await scaler_service.scale_down(5)
        
        # 应该只缩容到 min_workers
        assert len(scaler_service._workers) >= 2
    
    @pytest.mark.asyncio
    async def test_get_status(self, scaler_service):
        """测试获取状态"""
        await scaler_service.scale_up(3)
        
        status = scaler_service.get_status()
        
        assert status["enabled"] is True
        assert status["current_workers"] == 3
        assert status["max_workers"] == 10
    
    @pytest.mark.asyncio
    async def test_get_workers(self, scaler_service):
        """测试获取 Worker 列表"""
        await scaler_service.scale_up(2)
        
        workers = scaler_service.get_workers()
        
        assert len(workers) == 2
        assert workers[0]["status"] == "ready"
    
    @pytest.mark.asyncio
    async def test_record_metrics(self, scaler_service):
        """测试记录指标"""
        await scaler_service.scale_up(2)
        
        metrics = ScalingMetrics(
            cpu_usage=50.0,
            memory_usage=40.0,
            queue_length=50,
            latency_p99_ms=100.0,
            error_rate=1.0,
            active_workers=2
        )
        
        scaler_service.record_metrics(metrics)
        
        current = scaler_service.get_current_metrics()
        assert current is not None
        assert current.cpu_usage == 50.0
    
    @pytest.mark.asyncio
    async def test_should_scale_up(self, scaler_service):
        """测试扩容判断"""
        # 高 CPU
        metrics = ScalingMetrics(
            cpu_usage=90.0,
            queue_length=50,
            latency_p99_ms=100.0,
            error_rate=1.0
        )
        
        should, reason = scaler_service.should_scale_up(metrics)
        
        # 应该触发扩容
        assert should is True
    
    @pytest.mark.asyncio
    async def test_should_scale_down(self, scaler_service):
        """测试缩容判断"""
        # 先扩容一些 Worker
        await scaler_service.scale_up(5)
        
        # 模拟 Worker 空闲
        from datetime import timedelta
        for worker in scaler_service._workers.values():
            worker.last_heartbeat = datetime.utcnow() - timedelta(seconds=400)
        
        # 低 CPU，空闲 Worker
        metrics = ScalingMetrics(
            cpu_usage=10.0,
            queue_length=0,
            latency_p99_ms=50.0,
            error_rate=0.0,
            active_workers=5
        )
        
        should, reason = scaler_service.should_scale_down(metrics)
        
        # 应该触发缩容
        assert should is True


class TestScalingAction:
    """扩缩动作测试"""
    
    def test_action_values(self):
        """测试动作值"""
        assert ScalingAction.NONE.value == "none"
        assert ScalingAction.SCALE_UP.value == "scale_up"
        assert ScalingAction.SCALE_DOWN.value == "scale_down"


class TestScalingMetrics:
    """扩缩指标测试"""
    
    def test_create_metrics(self):
        """测试创建指标"""
        metrics = ScalingMetrics(
            cpu_usage=50.0,
            memory_usage=40.0,
            queue_length=100,
            latency_p99_ms=200.0,
            error_rate=2.0,
            active_workers=5
        )
        
        assert metrics.cpu_usage == 50.0
        assert metrics.queue_length == 100
        assert metrics.active_workers == 5


class TestScalingThresholds:
    """扩缩阈值测试"""
    
    def test_default_thresholds(self):
        """测试默认阈值"""
        thresholds = ScalingThresholds()
        
        assert thresholds.cpu_scale_up == 80.0
        assert thresholds.cpu_scale_down == 20.0
        assert thresholds.scale_up_duration_sec == 30
        assert thresholds.scale_down_cooldown_sec == 300
