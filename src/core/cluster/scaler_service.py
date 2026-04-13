"""
Scaler Service
F10: 自动扩缩容服务
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class ScalingAction(str, Enum):
    """扩缩动作"""
    NONE = "none"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"


@dataclass
class ScalingMetrics:
    """扩缩指标"""
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    queue_length: int = 0
    latency_p99_ms: float = 0.0
    error_rate: float = 0.0
    active_workers: int = 0
    pending_workers: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ScalingThresholds:
    """扩缩阈值配置"""
    # 扩容阈值
    cpu_scale_up: float = 80.0       # CPU > 80%
    queue_scale_up: int = 100        # 队列 > 100
    latency_scale_up: float = 5000.0  # P99 > 5s
    error_rate_scale_up: float = 5.0   # 错误率 > 5%
    
    # 扩容持续时间
    scale_up_duration_sec: int = 30
    
    # 缩容阈值
    cpu_scale_down: float = 20.0      # CPU < 20%
    queue_scale_down: int = 0         # 队列 = 0
    worker_idle_sec: int = 300        # Worker 空闲 > 5min
    
    # 缩容冷却时间
    scale_down_cooldown_sec: int = 300  # 5min


@dataclass
class ScalingConfig:
    """扩缩配置"""
    enabled: bool = True
    min_workers: int = 0
    max_workers: int = 10
    
    # 检查间隔
    check_interval_sec: int = 10
    
    # 创建/销毁 Worker 回调
    on_scale_up: Optional[Callable] = None
    on_scale_down: Optional[Callable] = None
    
    # 阈值
    thresholds: ScalingThresholds = field(default_factory=ScalingThresholds)


@dataclass
class WorkerInfo:
    """Worker 信息"""
    worker_id: str
    status: str = "creating"  # creating, ready, busy, draining, stopped
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    current_requests: int = 0
    completed_requests: int = 0
    
    @property
    def idle_time_sec(self) -> int:
        return (datetime.utcnow() - self.last_heartbeat).total_seconds()


class ScalerService:
    """
    Scaler 自动扩缩容服务
    
    职责:
    1. 收集系统指标
    2. 判断是否需要扩缩
    3. 执行扩缩操作
    4. 维护冷却时间
    """
    
    def __init__(self, config: ScalingConfig = None):
        self.config = config or ScalingConfig()
        self._workers: dict[str, WorkerInfo] = {}
        self._metrics_history: List[ScalingMetrics] = []
        self._last_scale_up_time: datetime = None
        self._last_scale_down_time: datetime = None
        self._running = False
        self._task = None
        
        logger.info(f"ScalerService initialized: min={self.config.min_workers}, "
                    f"max={self.config.max_workers}")
    
    # ==================== 指标收集 ====================
    
    def record_metrics(self, metrics: ScalingMetrics):
        """记录指标"""
        self._metrics_history.append(metrics)
        
        # 只保留最近 100 条
        if len(self._metrics_history) > 100:
            self._metrics_history = self._metrics_history[-100:]
    
    def get_current_metrics(self) -> Optional[ScalingMetrics]:
        """获取最新指标"""
        if not self._metrics_history:
            return None
        return self._metrics_history[-1]
    
    def get_avg_metrics(self, seconds: int = 60) -> ScalingMetrics:
        """获取平均指标（最近 N 秒）"""
        cutoff = datetime.utcnow() - timedelta(seconds=seconds)
        recent = [m for m in self._metrics_history if m.timestamp > cutoff]
        
        if not recent:
            return ScalingMetrics()
        
        return ScalingMetrics(
            cpu_usage=sum(m.cpu_usage for m in recent) / len(recent),
            memory_usage=sum(m.memory_usage for m in recent) / len(recent),
            queue_length=max(m.queue_length for m in recent),
            latency_p99_ms=max(m.latency_p99_ms for m in recent),
            error_rate=sum(m.error_rate for m in recent) / len(recent),
            active_workers=recent[-1].active_workers,
        )
    
    # ==================== 扩缩判定 ====================
    
    def should_scale_up(self, metrics: ScalingMetrics) -> tuple[bool, str]:
        """
        判断是否应该扩容
        
        Returns:
            (should_scale, reason)
        """
        thresholds = self.config.thresholds
        
        # 检查当前 Worker 数量
        if len(self._workers) >= self.config.max_workers:
            return False, "max_workers reached"
        
        # 检查冷却时间
        if self._last_scale_up_time:
            elapsed = (datetime.utcnow() - self._last_scale_up_time).total_seconds()
            if elapsed < 60:  # 至少 60 秒冷却
                return False, "scale_up_cooldown"
        
        # 检查扩容条件
        reasons = []
        
        if metrics.cpu_usage > thresholds.cpu_scale_up:
            reasons.append(f"CPU {metrics.cpu_usage:.1f}% > {thresholds.cpu_scale_up}%")
        
        if metrics.queue_length > thresholds.queue_scale_up:
            reasons.append(f"Queue {metrics.queue_length} > {thresholds.queue_scale_up}")
        
        if metrics.latency_p99_ms > thresholds.latency_scale_up:
            reasons.append(f"Latency P99 {metrics.latency_p99_ms:.0f}ms > {thresholds.latency_scale_up}ms")
        
        if metrics.error_rate > thresholds.error_rate_scale_up:
            reasons.append(f"Error rate {metrics.error_rate:.1f}% > {thresholds.error_rate_scale_up}%")
        
        if reasons:
            return True, ", ".join(reasons)
        
        return False, ""
    
    def should_scale_down(self, metrics: ScalingMetrics) -> tuple[bool, str]:
        """
        判断是否应该缩容
        
        Returns:
            (should_scale, reason)
        """
        thresholds = self.config.thresholds
        
        # 检查当前 Worker 数量
        if len(self._workers) <= self.config.min_workers:
            return False, "min_workers reached"
        
        # 检查冷却时间
        if self._last_scale_down_time:
            elapsed = (datetime.utcnow() - self._last_scale_down_time).total_seconds()
            if elapsed < thresholds.scale_down_cooldown_sec:
                remaining = thresholds.scale_down_cooldown_sec - elapsed
                return False, f"scale_down_cooldown ({remaining:.0f}s remaining)"
        
        # 检查缩容条件（必须同时满足）
        conditions = []
        
        if metrics.cpu_usage < thresholds.cpu_scale_down:
            conditions.append(f"CPU {metrics.cpu_usage:.1f}% < {thresholds.cpu_scale_down}%")
        
        if metrics.queue_length == thresholds.queue_scale_down:
            conditions.append("Queue = 0")
        
        # 检查空闲 Worker
        idle_workers = self._get_idle_workers()
        if idle_workers:
            conditions.append(f"{len(idle_workers)} idle workers")
        
        if metrics.cpu_usage < thresholds.cpu_scale_down and \
           metrics.queue_length == thresholds.queue_scale_down and \
           idle_workers:
            return True, f"{', '.join(conditions)}"
        
        return False, ""
    
    def _get_idle_workers(self) -> List[WorkerInfo]:
        """获取空闲 Worker"""
        idle_time = self.config.thresholds.worker_idle_sec
        return [
            w for w in self._workers.values()
            if w.status == "ready" and w.idle_time_sec > idle_time
        ]
    
    # ==================== 扩缩执行 ====================
    
    async def scale_up(self, count: int = 1) -> List[str]:
        """
        执行扩容
        
        Returns:
            新创建的 Worker ID 列表
        """
        if not self.config.enabled:
            logger.warning("Scaler is disabled")
            return []
        
        # 限制最大数量
        available = self.config.max_workers - len(self._workers)
        actual_count = min(count, available)
        
        if actual_count <= 0:
            logger.warning(f"Cannot scale up: at max capacity ({self.config.max_workers})")
            return []
        
        new_workers = []
        for i in range(actual_count):
            worker_id = f"worker-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{i}"
            
            worker = WorkerInfo(worker_id=worker_id, status="creating")
            self._workers[worker_id] = worker
            new_workers.append(worker_id)
            
            logger.info(f"Creating worker: {worker_id}")
            
            # 调用回调
            if self.config.on_scale_up:
                try:
                    await self.config.on_scale_up(worker_id)
                except Exception as e:
                    logger.error(f"on_scale_up callback failed: {e}")
        
        self._last_scale_up_time = datetime.utcnow()
        
        # 更新 Worker 状态
        for worker_id in new_workers:
            if worker_id in self._workers:
                self._workers[worker_id].status = "ready"
        
        logger.info(f"Scale up: {len(new_workers)} workers created")
        return new_workers
    
    async def scale_down(self, count: int = 1) -> List[str]:
        """
        执行缩容（平滑下线）
        
        Returns:
            已销毁的 Worker ID 列表
        """
        if not self.config.enabled:
            logger.warning("Scaler is disabled")
            return []
        
        # 选择空闲 Worker
        idle_workers = self._get_idle_workers()
        
        if not idle_workers:
            logger.info("No idle workers to scale down")
            return []
        
        actual_count = min(count, len(idle_workers))
        to_remove = idle_workers[:actual_count]
        
        removed = []
        for worker in to_remove:
            worker_id = worker.worker_id
            
            # 标记为 draining
            self._workers[worker_id].status = "draining"
            
            logger.info(f"Draining worker: {worker_id}")
            
            # 调用回调
            if self.config.on_scale_down:
                try:
                    await self.config.on_scale_down(worker_id)
                except Exception as e:
                    logger.error(f"on_scale_down callback failed: {e}")
            
            # 实际移除（简化版本）
            del self._workers[worker_id]
            removed.append(worker_id)
        
        self._last_scale_down_time = datetime.utcnow()
        
        logger.info(f"Scale down: {len(removed)} workers removed")
        return removed
    
    # ==================== 自动扩缩循环 ====================
    
    async def start(self, metrics_getter: Callable[[], ScalingMetrics]):
        """
        启动自动扩缩循环
        
        Args:
            metrics_getter: 获取指标的回调函数
        """
        if self._running:
            logger.warning("Scaler already running")
            return
        
        self._running = True
        logger.info("Scaler started")
        
        while self._running:
            try:
                # 获取指标
                metrics = metrics_getter()
                self.record_metrics(metrics)
                
                # 检查扩容
                should_up, reason_up = self.should_scale_up(metrics)
                if should_up:
                    logger.info(f"Scale up triggered: {reason_up}")
                    await self.scale_up()
                
                # 检查缩容
                should_down, reason_down = self.should_scale_down(metrics)
                if should_down:
                    logger.info(f"Scale down triggered: {reason_down}")
                    await self.scale_down()
                
            except Exception as e:
                logger.error(f"Scaler loop error: {e}")
            
            await asyncio.sleep(self.config.check_interval_sec)
    
    def stop(self):
        """停止自动扩缩"""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Scaler stopped")
    
    # ==================== 状态查询 ====================
    
    def get_status(self) -> dict:
        """获取 Scaler 状态"""
        metrics = self.get_current_metrics()
        
        return {
            "enabled": self.config.enabled,
            "mode": "auto",
            "min_workers": self.config.min_workers,
            "max_workers": self.config.max_workers,
            "current_workers": len(self._workers),
            "pending_workers": metrics.pending_workers if metrics else 0,
            "last_scale_up": self._last_scale_up_time.isoformat() if self._last_scale_up_time else None,
            "last_scale_down": self._last_scale_down_time.isoformat() if self._last_scale_down_time else None,
        }
    
    def get_workers(self) -> List[dict]:
        """获取所有 Worker"""
        return [
            {
                "worker_id": w.worker_id,
                "status": w.status,
                "created_at": w.created_at.isoformat(),
                "idle_time_sec": w.idle_time_sec,
                "current_requests": w.current_requests,
                "completed_requests": w.completed_requests,
            }
            for w in self._workers.values()
        ]


# ==================== 单例 ====================

scaler_service = ScalerService()
