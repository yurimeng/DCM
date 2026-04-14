"""
Job Queue Service - 抽象接口定义
Job Queue 与 Match Engine 解耦

来源: docs/Architecture.md Section 5.1
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional
import heapq


class QueueError(Exception):
    """队列异常基类"""
    pass


class QueueFullError(QueueError):
    """队列满"""
    pass


class InvalidJobError(QueueError):
    """Job 无效"""
    pass


class JobNotFoundError(QueueError):
    """Job 不存在"""
    pass


class QueueEmptyError(QueueError):
    """队列空"""
    pass


class RetryExhaustedError(QueueError):
    """重试次数耗尽"""
    pass


@dataclass
class QueueStats:
    """队列统计"""
    # Size metrics / 规模指标
    size: int = 0               # 当前队列大小
    max_size: int = 10000      # 最大容量
    jobs_in_progress: int = 0  # 处理中的 Job 数
    dead_letter_size: int = 0  # 死信队列大小
    
    # Performance metrics / 性能指标
    total_enqueued: int = 0      # 总入队数
    total_dequeued: int = 0      # 总出队数
    total_completed: int = 0     # 总完成数
    total_failed: int = 0       # 总失败数
    avg_wait_time_ms: float = 0 # 平均等待时间 (ms)
    avg_priority: float = 0.0   # 平均优先级
    
    @property
    def usage_percent(self) -> float:
        """使用率百分比"""
        if self.max_size <= 0:
            return 0.0
        return (self.size / self.max_size) * 100


@dataclass
class QueuedJob:
    """
    队列中的 Job 包装器
    
    用于 Priority Queue 排序
    """
    job_id: str
    user_id: str
    model: str
    model_family: str
    input_tokens: int
    output_tokens_limit: int
    bid_price: float
    max_latency: int
    priority: int = 0           # 优先级 (越大越高)
    enqueued_at: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0
    max_retries: int = 3
    dead_letter: bool = False
    
    @property
    def priority_score(self) -> float:
        """
        计算优先级分数
        
        公式: priority + (bid_price * 1000) + (1 / (enqueued_at + 1))
        
        排序: 分数越高越优先
        """
        # 时间因子: 等待越久权重越高
        wait_seconds = (datetime.utcnow() - self.enqueued_at).total_seconds()
        time_factor = min(wait_seconds / 3600, 1.0)  # 最多 1 小时
        
        # 综合分数
        return self.priority + (self.bid_price * 1000) + time_factor
    
    def __lt__(self, other: "QueuedJob") -> bool:
        """比较用于堆排序 (越大越优先)"""
        return self.priority_score > other.priority_score


class JobQueueService(ABC):
    """
    Job Queue Service - 抽象接口
    
    职责:
    - Job 的入队/出队
    - Priority 排序
    - 持久化存储
    - 死信队列处理
    
    注意: 与 Match Engine 完全解耦
    """
    
    @abstractmethod
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
        pass
    
    @abstractmethod
    def dequeue(self, timeout: Optional[float] = None) -> Optional[dict]:
        """
        出队 (最高 Priority)
        
        Args:
            timeout: 阻塞等待时间 (None = 非阻塞)
        
        Returns:
            Job 数据字典 或 None
        """
        pass
    
    @abstractmethod
    def peek(self, count: int = 10) -> List[dict]:
        """查看但不出队"""
        pass
    
    @abstractmethod
    def acknowledge(self, job_id: str) -> bool:
        """确认处理成功"""
        pass
    
    @abstractmethod
    def retry(self, job_id: str, delay: float = 0) -> bool:
        """
        重新入队
        
        Args:
            job_id: Job ID
            delay: 延迟秒数
        
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def dead_letter(self, job_id: str, reason: str) -> bool:
        """移入死信队列"""
        pass
    
    @abstractmethod
    def get_stats(self) -> QueueStats:
        """获取队列统计"""
        pass
    
    @abstractmethod
    def get_pending_jobs(self) -> List[dict]:
        """获取所有待处理 Job"""
        pass
    
    @abstractmethod
    def get_dead_letter_jobs(self) -> List[dict]:
        """获取死信队列"""
        pass
    
    @abstractmethod
    def requeue_dead_letter(self, job_id: str) -> bool:
        """从死信队列重新入队"""
        pass
    
    @abstractmethod
    def size(self) -> int:
        """获取当前队列大小"""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """清空队列"""
        pass
