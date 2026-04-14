"""
In-Memory Job Queue - MVP 实现

基于 heapq 的优先级队列，所有数据存储在内存中。
适用于小规模部署和开发测试。

来源: docs/Architecture.md Section 8 (MVP)
"""

import heapq
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

from .job_queue import (
    JobQueueService, 
    QueueStats, 
    QueuedJob,
    QueueFullError,
    InvalidJobError,
    JobNotFoundError
)


class InMemoryJobQueue(JobQueueService):
    """
    内存 Job Queue 实现
    
    特性:
    - Thread-safe (使用锁)
    - Priority 排序 (基于 heapq)
    - 内存存储 (重启丢失)
    - 死信队列支持
    - 重试机制
    
    限制:
    - 不支持分布式
    - 重启后数据丢失
    - 内存占用随队列增长
    """
    
    def __init__(self, max_size: int = 10000):
        """
        初始化队列
        
        Args:
            max_size: 最大队列长度 (防止内存溢出)
        """
        self._max_size = max_size
        
        # 优先级堆 (heapq 是最小堆, 取负数实现最大堆)
        self._heap: List[QueuedJob] = []
        
        # Job 数据存储 (job_id -> job_data)
        self._jobs: Dict[str, dict] = {}
        
        # 死信队列 (job_id -> (job_data, reason))
        self._dead_letters: Dict[str, tuple] = {}
        
        # 延迟重试队列 (job_id -> (job_data, retry_at))
        self._retry_queue: Dict[str, tuple] = {}
        
        # 统计
        self._stats = QueueStats()
        
        # 锁
        self._lock = threading.RLock()
        
        # 条件变量 (用于阻塞出队)
        self._not_empty = threading.Condition(self._lock)
    
    def enqueue(self, job_data: dict) -> str:
        """
        入队 job
        
        Args:
            job_data: Job 数据字典
        
        Returns:
            job_id
        
        Raises:
            QueueFullError: 队列满
            InvalidJobError: Job 无效
        """
        # 验证
        if not job_data:
            raise InvalidJobError("Job data is empty")
        
        # 支持 model 或 model_requirement 字段
        model = job_data.get("model") or job_data.get("model_requirement")
        # model 可选，不指定则由系统分配
        bid_price = job_data.get("bid_price")
        job_id = job_data.get("job_id")
        
        if not job_id:
            raise InvalidJobError("Missing required field: job_id")
        if not job_id:
            raise InvalidJobError("Missing required field: job_id")
        if not bid_price and bid_price != 0:
            raise InvalidJobError("Missing required field: bid_price")
        
        with self._lock:
            # 检查队列大小
            if len(self._heap) >= self._max_size:
                raise QueueFullError(f"Queue is full (max_size={self._max_size})")
            
            # 提取 QueuedJob
            queued_job = QueuedJob(
                job_id=job_id,
                user_id=job_data.get("user_id", ""),
                model=model,
                model_family=self._parse_family(model),
                input_tokens=job_data.get("input_tokens", 0),
                output_tokens_limit=job_data.get("output_tokens_limit", 1000),
                bid_price=bid_price,
                max_latency=job_data.get("max_latency", 60000),
                priority=job_data.get("priority", 0),
            )
            
            # 入堆
            heapq.heappush(self._heap, queued_job)
            
            # 存储数据
            self._jobs[job_id] = {
                **job_data,
                "queued_at": datetime.utcnow().isoformat(),
                "status": "pending",
            }
            
            # 统计
            self._stats.total_enqueued += 1
            self._stats.current_size = len(self._heap)
            
            # 通知等待的消费者
            self._not_empty.notify()
            
            return job_id
    
    def dequeue(self, timeout: Optional[float] = None) -> Optional[dict]:
        """
        出队 (最高 Priority)
        
        Args:
            timeout: 阻塞等待时间 (秒)
        
        Returns:
            Job 数据字典 或 None
        """
        with self._not_empty:
            # 首先检查延迟重试队列
            self._process_delayed_retries()
            
            while len(self._heap) == 0:
                if timeout is None:
                    # 非阻塞, 立即返回
                    return None
                
                # 阻塞等待
                remaining = timeout
                start = time.time()
                
                if remaining <= 0:
                    return None
                
                self._not_empty.wait(timeout=remaining)
                
                # 检查超时
                elapsed = time.time() - start
                if elapsed >= timeout:
                    return None
                
                # 再次检查延迟重试
                self._process_delayed_retries()
            
            # 出堆
            queued_job = heapq.heappop(self._heap)
            
            # 更新状态
            if queued_job.job_id in self._jobs:
                self._jobs[queued_job.job_id]["dequeued_at"] = datetime.utcnow().isoformat()
            
            # 统计
            self._stats.current_size = len(self._heap)
            
            return self._jobs.get(queued_job.job_id)
    
    def peek(self, count: int = 10) -> List[dict]:
        """查看但不出队"""
        with self._lock:
            # 获取前 N 个 (不破坏堆)
            jobs = []
            for queued_job in sorted(self._heap, reverse=True)[:count]:
                job_data = self._jobs.get(queued_job.job_id)
                if job_data:
                    jobs.append(job_data)
            return jobs
    
    def acknowledge(self, job_id: str) -> bool:
        """确认处理成功"""
        with self._lock:
            if job_id not in self._jobs:
                return False
            
            # 更新状态
            self._jobs[job_id]["status"] = "completed"
            self._jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
            
            # 统计
            self._stats.total_dequeued += 1
            self._stats.total_completed += 1
            
            return True
    
    def retry(self, job_id: str, delay: float = 0) -> bool:
        """
        重新入队
        
        Args:
            job_id: Job ID
            delay: 延迟秒数
        
        Returns:
            是否成功
        """
        with self._lock:
            if job_id not in self._jobs:
                return False
            
            job_data = self._jobs[job_id]
            
            if delay > 0:
                # 加入延迟重试队列
                self._retry_queue[job_id] = (
                    job_data,
                    time.time() + delay
                )
                job_data["status"] = "retry_pending"
                job_data["retry_count"] = job_data.get("retry_count", 0) + 1
            else:
                # 立即重试
                queued_job = QueuedJob(
                    job_id=job_data["job_id"],
                    user_id=job_data.get("user_id", ""),
                    model=job_data["model"],
                    model_family=self._parse_family(job_data["model"]),
                    input_tokens=job_data.get("input_tokens", 0),
                    output_tokens_limit=job_data.get("output_tokens_limit", 1000),
                    bid_price=job_data["bid_price"],
                    max_latency=job_data.get("max_latency", 60000),
                    priority=job_data.get("priority", 0),
                    retry_count=job_data.get("retry_count", 0) + 1,
                )
                
                heapq.heappush(self._heap, queued_job)
                job_data["status"] = "pending"
                self._not_empty.notify()
            
            return True
    
    def dead_letter(self, job_id: str, reason: str) -> bool:
        """移入死信队列"""
        with self._lock:
            if job_id not in self._jobs:
                return False
            
            job_data = self._jobs[job_id]
            job_data["status"] = "dead_letter"
            job_data["dead_letter_reason"] = reason
            job_data["dead_letter_at"] = datetime.utcnow().isoformat()
            
            # 移入死信队列
            self._dead_letters[job_id] = (job_data, reason)
            
            # 从主队列移除 (如果还在)
            # 注意: 已经出堆的 job 不在 _heap 中
            
            # 统计
            self._stats.total_failed += 1
            
            return True
    
    def get_stats(self) -> QueueStats:
        """获取队列统计"""
        with self._lock:
            stats = QueueStats(
                size=len(self._heap),
                max_size=self._max_size,
                total_enqueued=self._stats.total_enqueued,
                total_dequeued=self._stats.total_dequeued,
                total_completed=self._stats.total_completed,
                total_failed=self._stats.total_failed,
            )
            
            # 计算平均等待时间
            if self._stats.total_dequeued > 0:
                total_wait = sum(
                    self._get_wait_time(j)
                    for j in self._jobs.values()
                    if j.get("status") in ("completed", "dequeued")
                )
                stats.avg_wait_time_ms = total_wait / self._stats.total_dequeued
            
            return stats
    
    def get_pending_jobs(self) -> List[dict]:
        """获取所有待处理 Job (排除已完成的)"""
        with self._lock:
            return [
                self._jobs[job_id]
                for job_id, queued_job in zip(
                    [j.job_id for j in self._heap],
                    self._heap
                )
                if job_id in self._jobs
                and self._jobs[job_id].get("status") != "completed"
            ]
    
    def get_dead_letter_jobs(self) -> List[dict]:
        """获取死信队列"""
        with self._lock:
            return [
                {"job": job_data, "reason": reason}
                for job_data, reason in self._dead_letters.values()
            ]
    
    def requeue_dead_letter(self, job_id: str) -> bool:
        """从死信队列重新入队"""
        with self._lock:
            if job_id not in self._dead_letters:
                return False
            
            job_data, _ = self._dead_letters.pop(job_id)
            
            # 重新入队
            queued_job = QueuedJob(
                job_id=job_data["job_id"],
                user_id=job_data.get("user_id", ""),
                model=job_data["model"],
                model_family=self._parse_family(job_data["model"]),
                input_tokens=job_data.get("input_tokens", 0),
                output_tokens_limit=job_data.get("output_tokens_limit", 1000),
                bid_price=job_data["bid_price"],
                max_latency=job_data.get("max_latency", 60000),
                priority=job_data.get("priority", 0),
            )
            
            heapq.heappush(self._heap, queued_job)
            job_data["status"] = "pending"
            
            self._not_empty.notify()
            
            return True
    
    def size(self) -> int:
        """获取当前队列大小"""
        with self._lock:
            return len(self._heap)
    
    def clear(self) -> None:
        """清空队列"""
        with self._lock:
            self._heap.clear()
            self._jobs.clear()
            self._dead_letters.clear()
            self._retry_queue.clear()
            self._stats = QueueStats()
    
    def _process_delayed_retries(self) -> None:
        """处理延迟重试队列"""
        now = time.time()
        to_retry = [
            (job_id, job_data)
            for job_id, (job_data, retry_at) in self._retry_queue.items()
            if retry_at <= now
        ]
        
        for job_id, job_data in to_retry:
            self._retry_queue.pop(job_id, None)
            
            queued_job = QueuedJob(
                job_id=job_data["job_id"],
                user_id=job_data.get("user_id", ""),
                model=job_data["model"],
                model_family=self._parse_family(job_data["model"]),
                input_tokens=job_data.get("input_tokens", 0),
                output_tokens_limit=job_data.get("output_tokens_limit", 1000),
                bid_price=job_data["bid_price"],
                max_latency=job_data.get("max_latency", 60000),
                priority=job_data.get("priority", 0),
                retry_count=job_data.get("retry_count", 0) + 1,
            )
            
            heapq.heappush(self._heap, queued_job)
            job_data["status"] = "pending"
            
            self._not_empty.notify()
    
    def _get_wait_time(self, job_data: dict) -> float:
        """计算 Job 等待时间 (ms)"""
        if "queued_at" not in job_data or "dequeued_at" not in job_data:
            return 0
        
        try:
            queued = datetime.fromisoformat(job_data["queued_at"])
            dequeued = datetime.fromisoformat(job_data["dequeued_at"])
            return (dequeued - queued).total_seconds() * 1000
        except:
            return 0
    
    def _parse_family(self, model: str) -> str:
        """从 model 字符串解析 family"""
        import re
        
        if not model:
            return "*"
        
        # 格式: qwen2.5:7b, llama3:8b-instruct, gemma4:e4b
        base = model.split(":")[0]
        match = re.match(r'^([a-zA-Z]+)', base)
        
        return match.group(1).lower() if match else base.lower()


# 全局单例 (MVP 阶段)
_job_queue: Optional[InMemoryJobQueue] = None
_queue_lock = threading.Lock()


def get_job_queue() -> InMemoryJobQueue:
    """获取全局 Job Queue 实例"""
    global _job_queue
    
    with _queue_lock:
        if _job_queue is None:
            _job_queue = InMemoryJobQueue(max_size=10000)
        return _job_queue


def reset_job_queue() -> None:
    """重置全局 Job Queue (用于测试)"""
    global _job_queue
    
    with _queue_lock:
        if _job_queue is not None:
            _job_queue.clear()
        _job_queue = None
