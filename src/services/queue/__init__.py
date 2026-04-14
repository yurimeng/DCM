"""
Job Queue Module - Job 队列服务
Job Queue 与 Match Engine 解耦

模块结构:
- job_queue.py: 抽象接口定义
- in_memory_queue.py: 内存队列实现 (MVP)
- redis_queue.py: Redis 队列实现 (分布式)

使用示例:
    # 根据配置自动选择 (推荐)
    from src.services.queue import create_queue
    queue = create_queue()
    
    # 内存队列 (MVP)
    from src.services.queue import get_job_queue
    queue = get_job_queue()
    
    # Redis 队列 (分布式)
    from src.services.queue import get_redis_queue
    queue = get_redis_queue(url="redis://localhost:6379/0")
"""

from .job_queue import JobQueueService, QueueStats
from .in_memory_queue import (
    InMemoryJobQueue, 
    get_job_queue, 
    reset_job_queue
)
from .redis_queue import RedisJobQueue, get_redis_queue


def create_queue(in_memory: bool = None) -> JobQueueService:
    """
    根据配置创建 Queue 实例
    
    Args:
        in_memory: True  → 使用 InMemoryQueue
                   False → 使用 RedisQueue
                   None  → 从配置文件读取
    
    Returns:
        JobQueueService 实例
    """
    # 从配置读取
    if in_memory is None:
        in_memory = _get_config_in_memory()
    
    if in_memory:
        return get_job_queue()
    else:
        return _create_redis_queue()


def _get_config_in_memory() -> bool:
    """从配置文件读取 in_memory 设置"""
    try:
        import yaml
        with open("config/models.yaml", "r") as f:
            config = yaml.safe_load(f)
        return config.get("queue", {}).get("in_memory", True)
    except Exception:
        return True  # 默认使用内存队列


def _create_redis_queue() -> RedisJobQueue:
    """从配置创建 Redis Queue"""
    try:
        import yaml
        with open("config/models.yaml", "r") as f:
            config = yaml.safe_load(f)
        
        queue_config = config.get("queue", {})
        redis_config = queue_config.get("redis", {})
        
        return get_redis_queue(
            host=redis_config.get("host", "localhost"),
            port=redis_config.get("port", 6379),
            db=redis_config.get("db", 0),
            password=redis_config.get("password"),
            max_size=queue_config.get("max_size", 10000),
        )
    except Exception:
        # 配置读取失败，使用默认值
        return get_redis_queue()


__all__ = [
    # Abstract / 抽象
    "JobQueueService",
    "QueueStats",
    # Factory / 工厂
    "create_queue",
    # In-Memory / 内存
    "InMemoryJobQueue",
    "get_job_queue",
    "reset_job_queue",
    # Redis / Redis
    "RedisJobQueue",
    "get_redis_queue",
]
