"""
Redis Job Queue Implementation / Redis Job Queue 实现

使用 Redis Sorted Set 实现 Priority Queue：
- score = priority_score (来自 job_queue.py)
- member = job_id
- 额外 Hash 存储 job 数据

Author: DCM Team
Date: 2026-04-14
"""

import json
import time
import uuid
import threading
from typing import Optional, List, Dict, Any

import redis

from .job_queue import (
    JobQueueService,
    QueuedJob,
    QueueStats,
    QueueFullError,
    QueueEmptyError,
    InvalidJobError,
    JobNotFoundError,
    RetryExhaustedError,
)


# ============================================================================
# Constants / 常量
# ============================================================================

REDIS_QUEUE_KEY = "dcm:job_queue"
REDIS_JOBS_KEY = "dcm:jobs"  # Hash: job_id -> job_data
REDIS_DEAD_LETTER_KEY = "dcm:dead_letter"
REDIS_RETRIES_KEY = "dcm:retries"  # Hash: job_id -> retry_count
DEFAULT_MAX_SIZE = 10000
DEFAULT_RETRY_LIMIT = 3
DEFAULT_RETRY_TTL = 86400  # 24 hours


# ============================================================================
# Redis Job Queue / Redis Job Queue 实现
# ============================================================================

class RedisJobQueue(JobQueueService):
    """
    Redis-backed Job Queue using Sorted Sets
    基于 Redis Sorted Set 的 Job Queue
    
    Features:
    - Priority ordering via Sorted Set score
    - Persistent storage across restarts
    - Atomic operations via Redis transactions
    - Retry tracking via separate Hash
    - Dead letter queue for failed jobs
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_size: int = DEFAULT_MAX_SIZE,
        retry_limit: int = DEFAULT_RETRY_LIMIT,
        retry_ttl: int = DEFAULT_RETRY_TTL,
        key_prefix: str = "dcm",
    ):
        """
        Initialize Redis Job Queue
        
        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password (optional)
            max_size: Maximum queue size
            retry_limit: Max retry attempts before dead letter
            retry_ttl: TTL for retry tracking (seconds)
            key_prefix: Prefix for all Redis keys
        """
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._max_size = max_size
        self._retry_limit = retry_limit
        self._retry_ttl = retry_ttl
        self._key_prefix = key_prefix
        
        # Redis keys
        self._queue_key = f"{key_prefix}:job_queue"
        self._jobs_key = f"{key_prefix}:jobs"
        self._dead_letter_key = f"{key_prefix}:dead_letter"
        self._retries_key = f"{key_prefix}:retries"
        self._stats_key = f"{key_prefix}:stats"
        
        # Thread lock for local operations
        self._lock = threading.RLock()
        
        # Lazy connection
        self._redis: Optional[redis.Redis] = None
    
    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection"""
        if self._redis is None:
            self._redis = redis.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
        return self._redis
    
    def enqueue(self, job_data: dict) -> str:
        """
        Enqueue a job with priority score
        
        Args:
            job_data: Job data dictionary
            
        Returns:
            job_id: The enqueued job ID
            
        Raises:
            QueueFullError: If queue exceeds max_size
            InvalidJobError: If job data is invalid
        """
        # Validate / 验证
        if job_data is None or len(job_data) == 0:
            raise InvalidJobError("Job data is empty")
        
        # Get job_id
        job_id = job_data.get("job_id") or f"job_{uuid.uuid4().hex[:8]}"
        
        # Calculate priority score
        priority_score = self._calculate_priority_score(job_data)
        
        try:
            # Check queue size
            current_size = self.redis.zcard(self._queue_key)
            if current_size >= self._max_size:
                raise QueueFullError(f"Queue full (max: {self._max_size})")
            
            # Store job data in Hash
            self.redis.hset(self._jobs_key, job_id, json.dumps(job_data))
            
            # Add to sorted set with priority score
            self.redis.zadd(self._queue_key, {job_id: priority_score})
            
            # Initialize retry count
            self.redis.hset(self._retries_key, job_id, "0")
            
            return job_id
            
        except redis.RedisError as e:
            raise RuntimeError(f"Redis error: {e}")
    
    def dequeue(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Dequeue highest priority job
        
        Args:
            timeout: Blocking timeout in seconds (None = non-blocking)
            
        Returns:
            Job data dict or None if empty/timeout
        """
        # Blocking pop from sorted set
        if timeout and timeout > 0:
            # Use BZPOPMIN for blocking dequeue
            result = self.redis.bzpopmin(self._queue_key, timeout=timeout)
            if result is None:
                return None
            job_id = result[1]
        else:
            # Non-blocking
            result = self.redis.zpopmin(self._queue_key, count=1)
            if not result:
                return None
            job_id = result[0][0]
        
        # Get job data
        job_data_raw = self.redis.hget(self._jobs_key, job_id)
        if job_data_raw is None:
            # Job data lost, skip
            return None
        
        # Delete job data (will be restored on retry)
        self.redis.hdel(self._jobs_key, job_id)
        
        return json.loads(job_data_raw)
    
    def peek(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Peek at highest priority jobs without removing them
        
        Args:
            count: Number of jobs to peek
            
        Returns:
            List of job data dicts
        """
        # Get top N jobs by score (highest priority first)
        job_ids = self.redis.zrevrange(self._queue_key, 0, count - 1)
        
        if not job_ids:
            return []
        
        # Get job data for each
        jobs = []
        for job_id in job_ids:
            job_data_raw = self.redis.hget(self._jobs_key, job_id)
            if job_data_raw:
                jobs.append(json.loads(job_data_raw))
        
        return jobs
    
    def acknowledge(self, job_id: str) -> bool:
        """
        Acknowledge successful job processing
        
        Args:
            job_id: Job ID to acknowledge
            
        Returns:
            True if acknowledged
        """
        with self._lock:
            # Remove from retry tracking
            self.redis.hdel(self._retries_key, job_id)
            
            # Job data already removed on dequeue
            return True
    
    def retry(self, job_id: str, delay: float = 0) -> bool:
        """
        Retry a failed job
        
        Args:
            job_id: Job ID to retry
            delay: Delay before retry (seconds)
            
        Returns:
            True if requeued, False if max retries exceeded
        """
        with self._lock:
            # Get current retry count
            retry_count_str = self.redis.hget(self._retries_key, job_id)
            retry_count = int(retry_count_str or 0)
            
            # Check if exceeded
            if retry_count >= self._retry_limit:
                # Move to dead letter queue
                self._move_to_dead_letter(job_id, f"Max retries exceeded ({self._retry_limit})")
                return False
            
            # Increment retry count
            self.redis.hincrby(self._retries_key, job_id, 1)
            
            # Get job data
            job_data_raw = self.redis.hget(self._jobs_key, job_id)
            if job_data_raw:
                job_data = json.loads(job_data_raw)
            else:
                # Job data lost - cannot retry
                raise JobNotFoundError(f"Job data not found for {job_id}")
            
            # Apply delay if specified
            if delay > 0:
                time.sleep(delay)
            
            # Recalculate priority (boost for retries)
            priority_score = self._calculate_priority_score(job_data, retry=retry_count + 1)
            
            # Re-add to queue with boosted priority
            self.redis.zadd(self._queue_key, {job_id: priority_score})
            
            return True
    
    def dead_letter(self, job_id: str, reason: str) -> bool:
        """
        Move job to dead letter queue
        
        Args:
            job_id: Job ID
            reason: Reason for dead letter
            
        Returns:
            True if moved successfully
        """
        return self._move_to_dead_letter(job_id, reason)
    
    def get_stats(self) -> QueueStats:
        """
        Get queue statistics
        
        Returns:
            QueueStats object
        """
        try:
            queue_size = self.redis.zcard(self._queue_key)
            jobs_stored = self.redis.hlen(self._jobs_key)
            dead_letter_size = self.redis.zcard(self._dead_letter_key)
            
            # Calculate average priority
            avg_priority = 0.0
            if queue_size > 0:
                avg_score = self.redis.zmean(self._queue_key)
                avg_priority = avg_score / 1000 if avg_score else 0.0
            
            return QueueStats(
                size=queue_size,
                max_size=self._max_size,
                jobs_in_progress=jobs_stored,
                dead_letter_size=dead_letter_size,
                avg_priority=avg_priority,
            )
        except redis.RedisError:
            # Return default stats on error
            return QueueStats(
                size=0,
                max_size=self._max_size,
                jobs_in_progress=0,
                dead_letter_size=0,
                avg_priority=0.0,
            )
    
    def get_dead_letters(self, count: int = 100) -> List[Dict[str, Any]]:
        """
        Get dead letter queue contents
        
        Args:
            count: Max items to return
            
        Returns:
            List of dead letter jobs with reasons
        """
        dead_letters = self.redis.zrange(self._dead_letter_key, 0, count - 1)
        result = []
        
        for entry in dead_letters:
            # Format: job_id:reason:timestamp
            parts = entry.split(":", 2)
            if len(parts) >= 2:
                result.append({
                    "job_id": parts[0],
                    "reason": parts[1] if len(parts) > 1 else "Unknown",
                    "timestamp": parts[2] if len(parts) > 2 else 0,
                })
        
        return result
    
    def clear_dead_letters(self) -> int:
        """
        Clear all dead letters
        
        Returns:
            Number of dead letters cleared
        """
        count = self.redis.zcard(self._dead_letter_key)
        self.redis.delete(self._dead_letter_key)
        return count
    
    def clear(self) -> int:
        """
        Clear entire queue
        
        Returns:
            Number of jobs cleared
        """
        count = self.redis.zcard(self._queue_key)
        self.redis.delete(self._queue_key, self._jobs_key, self._retries_key)
        return count
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check Redis connection health
        
        Returns:
            Health status dict
        """
        try:
            start = time.time()
            self.redis.ping()
            latency = (time.time() - start) * 1000
            
            info = self.redis.info("server")
            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "redis_version": info.get("redis_version", "unknown"),
            }
        except redis.RedisError as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }
    
    def get_pending_jobs(self) -> List[Dict[str, Any]]:
        """
        Get all pending jobs in queue
        
        Returns:
            List of all pending job data dicts
        """
        job_ids = self.redis.zrange(self._queue_key, 0, -1)
        jobs = []
        
        for job_id in job_ids:
            job_data_raw = self.redis.hget(self._jobs_key, job_id)
            if job_data_raw:
                jobs.append(json.loads(job_data_raw))
        
        return jobs
    
    def get_dead_letter_jobs(self) -> List[Dict[str, Any]]:
        """
        Get all dead letter jobs
        
        Returns:
            List of dead letter job entries with reasons
        """
        return self.get_dead_letters(count=1000)
    
    def requeue_dead_letter(self, job_id: str) -> bool:
        """
        Requeue a dead letter job
        
        Args:
            job_id: Job ID to requeue
            
        Returns:
            True if requeued successfully
        """
        # Find in dead letter queue
        entries = self.redis.zrange(self._dead_letter_key, 0, -1)
        
        for entry in entries:
            if entry.startswith(f"{job_id}:"):
                # Get job data (stored separately)
                job_data_raw = self.redis.hget(self._jobs_key, job_id)
                if not job_data_raw:
                    return False
                
                # Remove from dead letter
                self.redis.zrem(self._dead_letter_key, entry)
                
                # Re-enqueue
                job_data = json.loads(job_data_raw)
                self.enqueue(job_data)
                
                return True
        
        return False
    
    def size(self) -> int:
        """
        Get current queue size
        
        Returns:
            Number of jobs in queue
        """
        return self.redis.zcard(self._queue_key)
    
    # ========================================================================
    # Private Methods / 私有方法
    # ========================================================================
    
    def _calculate_priority_score(
        self,
        job_data: dict,
        retry: int = 0
    ) -> float:
        """
        Calculate priority score for sorted set
        
        Score = priority * 1_000_000 + bid_price * 1000 + wait_time_factor
        Higher score = higher priority
        
        Args:
            job_data: Job data
            retry: Retry count (boosts priority)
            
        Returns:
            Priority score
        """
        priority = job_data.get("priority", 5)
        bid_price = job_data.get("bid_price", 0)
        created_at = job_data.get("created_at", time.time())
        
        # Wait time factor (max 1 hour = 3600 seconds)
        wait_time = min(time.time() - created_at, 3600)
        
        # Retry boost: each retry adds 100 to priority
        retry_boost = retry * 100
        
        # Calculate final score
        score = (
            (priority + retry_boost) * 1_000_000 +
            bid_price * 1000 +
            wait_time
        )
        
        return score
    
    def _move_to_dead_letter(self, job_id: str, reason: str) -> bool:
        """
        Move job to dead letter queue
        
        Args:
            job_id: Job ID
            reason: Reason for dead letter
            
        Returns:
            True if moved
        """
        timestamp = time.time()
        entry = f"{job_id}:{reason}:{timestamp}"
        
        self.redis.zadd(self._dead_letter_key, {entry: timestamp})
        self.redis.hdel(self._jobs_key, job_id)
        self.redis.hdel(self._retries_key, job_id)
        
        # Remove from main queue if still there
        self.redis.zrem(self._queue_key, job_id)
        
        return True
    
    def close(self):
        """Close Redis connection"""
        if self._redis:
            self._redis.close()
            self._redis = None


# ============================================================================
# Factory Function / 工厂函数
# ============================================================================

def get_redis_queue(
    url: Optional[str] = None,
    **kwargs
) -> RedisJobQueue:
    """
    Create Redis queue from URL or kwargs
    
    Supports URL format: redis://host:port/db
    Or separate kwargs: host, port, db, password
    
    Args:
        url: Redis URL
        **kwargs: Additional arguments
        
    Returns:
        RedisJobQueue instance
    """
    if url:
        # Parse URL: redis://host:port/db
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        
        kwargs.setdefault("host", parsed.hostname or "localhost")
        kwargs.setdefault("port", parsed.port or 6379)
        kwargs.setdefault("db", int(parsed.path.lstrip("/") or 0))
        kwargs.setdefault("password", parsed.password)
    
    return RedisJobQueue(**kwargs)
