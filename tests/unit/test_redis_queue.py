"""
Unit Tests for Redis Job Queue / Redis Job Queue 单元测试

Requires: pip install redis
Optional: Redis server running on localhost:6379

If Redis is not available, tests will be skipped.
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch

# Try to import redis, skip if not available
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from src.services.queue.job_queue import (
    JobQueueService,
    QueueStats,
    InvalidJobError,
    QueueFullError,
    JobNotFoundError,
)

# Skip all tests if redis not available
pytestmark = pytest.mark.skipif(
    not REDIS_AVAILABLE,
    reason="Redis not installed or not available"
)


# ============================================================================
# Mock Redis Queue for Testing / 测试用 Mock Redis Queue
# ============================================================================

class MockRedis:
    """Mock Redis for testing without real Redis server"""
    
    def __init__(self, *args, **kwargs):
        self._data = {}  # key -> {sorted_set: dict, hash: dict}
        self._locks = {}  # key -> threading.Lock
    
    def _get_lock(self, key):
        if key not in self._locks:
            self._locks[key] = threading.RLock()
        return self._locks[key]
    
    def _ensure_key(self, key, key_type):
        if key not in self._data:
            self._data[key] = {"sorted_set": {}, "hash": {}, "zset_scores": {}}
        return self._data[key]
    
    def zadd(self, key, mapping):
        """Add to sorted set: {member: score}"""
        data = self._ensure_key(key, "sorted_set")
        data["sorted_set"].update(mapping)
        data["zset_scores"].update(mapping)
        return len(mapping)
    
    def zcard(self, key):
        """Count sorted set members"""
        if key not in self._data:
            return 0
        return len(self._data[key]["sorted_set"])
    
    def zpopmin(self, key, count=1):
        """Pop lowest score members"""
        if key not in self._data:
            return []
        data = self._data[key]
        if not data["sorted_set"]:
            return []
        
        # Sort by score ascending
        sorted_items = sorted(
            data["sorted_set"].items(),
            key=lambda x: x[1]
        )[:count]
        
        # Remove popped items
        for member, score in sorted_items:
            del data["sorted_set"][member]
            del data["zset_scores"][member]
        
        return [(m, s) for m, s in sorted_items]
    
    def zrevrange(self, key, start, end):
        """Get members by rank (highest first)"""
        if key not in self._data:
            return []
        data = self._data[key]
        if not data["sorted_set"]:
            return []
        
        # Sort by score descending
        sorted_items = sorted(
            data["sorted_set"].items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Handle -1 end
        if end == -1:
            end = len(sorted_items)
        else:
            end = end + 1
        
        return [m for m, s in sorted_items[start:end]]
    
    def zrem(self, key, member):
        """Remove member from sorted set"""
        if key not in self._data:
            return 0
        data = self._data[key]
        if member in data["sorted_set"]:
            del data["sorted_set"][member]
            if member in data["zset_scores"]:
                del data["zset_scores"][member]
            return 1
        return 0
    
    def zrange(self, key, start, end):
        """Get members by rank (lowest first)"""
        if key not in self._data:
            return []
        data = self._data[key]
        if not data["sorted_set"]:
            return []
        
        sorted_items = sorted(data["sorted_set"].items(), key=lambda x: x[1])
        
        if end == -1:
            end = len(sorted_items)
        else:
            end = end + 1
        
        return [m for m, s in sorted_items[start:end]]
    
    def zmean(self, key):
        """Get average score (not real Redis, but needed for stats)"""
        if key not in self._data:
            return 0
        data = self._data[key]
        if not data["zset_scores"]:
            return 0
        return sum(data["zset_scores"].values()) / len(data["zset_scores"])
    
    def hset(self, key, field, value):
        """Set hash field"""
        data = self._ensure_key(key, "hash")
        data["hash"][field] = value
        return 1
    
    def hget(self, key, field):
        """Get hash field"""
        if key not in self._data:
            return None
        return self._data[key]["hash"].get(field)
    
    def hdel(self, key, *fields):
        """Delete hash fields"""
        if key not in self._data:
            return 0
        count = 0
        for field in fields:
            if field in self._data[key]["hash"]:
                del self._data[key]["hash"][field]
                count += 1
        return count
    
    def hlen(self, key):
        """Count hash fields"""
        if key not in self._data:
            return 0
        return len(self._data[key]["hash"])
    
    def hincrby(self, key, field, amount):
        """Increment hash field"""
        data = self._ensure_key(key, "hash")
        current = int(data["hash"].get(field, 0))
        new_value = current + amount
        data["hash"][field] = str(new_value)
        return new_value
    
    def delete(self, *keys):
        """Delete keys"""
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                count += 1
        return count
    
    def zcard(self, key):
        """Count sorted set"""
        if key not in self._data:
            return 0
        return len(self._data[key]["sorted_set"])
    
    def ping(self):
        """Ping (always success)"""
        return True
    
    def info(self, section=None):
        """Get info"""
        return {"redis_version": "7.0.0-mock"}
    
    def close(self):
        """Close (no-op)"""
        pass
    
    # For BZPOPMIN mock
    def bzpopmin(self, key, timeout=0):
        """Blocking pop (non-blocking in mock)"""
        result = self.zpopmin(key, 1)
        if result:
            return (key, result[0][0], result[0][1])
        return None


# ============================================================================
# Test Cases / 测试用例
# ============================================================================

class TestRedisJobQueueBasic:
    """Basic Redis Queue Tests / Redis Queue 基本测试"""
    
    @pytest.fixture
    def queue(self):
        """Create queue with mock Redis"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import RedisJobQueue
            q = RedisJobQueue(host="localhost", port=6379)
            q._redis = mock_redis
            yield q
    
    def test_enqueue_job(self, queue):
        """Test enqueue job"""
        job_data = {
            "job_id": "test-001",
            "model": "llama3-8b",
            "bid_price": 0.5,
            "priority": 5,
        }
        
        job_id = queue.enqueue(job_data)
        
        assert job_id == "test-001"
        assert queue.redis.zcard(queue._queue_key) == 1
    
    def test_dequeue_job(self, queue):
        """Test dequeue job"""
        job_data = {
            "job_id": "test-002",
            "model": "llama3-8b",
            "bid_price": 0.5,
        }
        
        queue.enqueue(job_data)
        retrieved = queue.dequeue()
        
        assert retrieved["job_id"] == "test-002"
        assert queue.redis.zcard(queue._queue_key) == 0
    
    def test_peek_jobs(self, queue):
        """Test peek without removing"""
        for i in range(3):
            queue.enqueue({
                "job_id": f"peek-{i}",
                "model": "llama3-8b",
                "bid_price": 0.5,
            })
        
        peeked = queue.peek(2)
        
        assert len(peeked) == 2
        # Queue should still have all jobs
        assert queue.redis.zcard(queue._queue_key) == 3
    
    def test_acknowledge_job(self, queue):
        """Test acknowledge completed job"""
        job_data = {
            "job_id": "ack-test",
            "model": "llama3-8b",
        }
        
        queue.enqueue(job_data)
        queue.acknowledge("ack-test")
        
        # Should be clean
        assert queue.redis.hget(queue._retries_key, "ack-test") is None


class TestRedisJobQueuePriority:
    """Priority Queue Tests / 优先级队列测试"""
    
    @pytest.fixture
    def queue(self):
        """Create queue with mock Redis"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import RedisJobQueue
            q = RedisJobQueue(host="localhost", port=6379)
            q._redis = mock_redis
            yield q
    
    def test_priority_ordering(self, queue):
        """Test jobs are ordered by priority (score-based)"""
        # Enqueue with different priorities
        queue.enqueue({"job_id": "low", "priority": 1, "bid_price": 0.1})
        queue.enqueue({"job_id": "high", "priority": 10, "bid_price": 0.1})
        queue.enqueue({"job_id": "medium", "priority": 5, "bid_price": 0.1})
        
        # All should be enqueued
        assert queue.size() == 3
        
        # Peek to check order (highest priority first due to score)
        jobs = queue.peek(3)
        assert len(jobs) == 3
        # First should be high priority (highest score)
        assert jobs[0]["job_id"] == "high"
    
    def test_bid_price_affects_priority(self, queue):
        """Test bid_price increases priority"""
        queue.enqueue({"job_id": "low-bid", "priority": 5, "bid_price": 0.1})
        queue.enqueue({"job_id": "high-bid", "priority": 5, "bid_price": 1.0})
        
        jobs = queue.peek(2)
        # High bid should come first when same priority
        assert jobs[0]["job_id"] == "high-bid"


class TestRedisJobQueueDeadLetter:
    """Dead Letter Queue Tests / 死信队列测试"""
    
    @pytest.fixture
    def queue(self):
        """Create queue with mock Redis"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import RedisJobQueue
            q = RedisJobQueue(host="localhost", port=6379, retry_limit=2)
            q._redis = mock_redis
            yield q
    
    def test_dead_letter_after_max_retries(self, queue):
        """Test job goes to dead letter after max retries"""
        job_data = {
            "job_id": "failing",
            "model": "llama3-8b",
        }
        
        queue.enqueue(job_data)
        
        # Retry twice (at limit)
        assert queue.retry("failing") is True
        assert queue.retry("failing") is True
        
        # Third retry should fail -> dead letter
        assert queue.retry("failing") is False
        
        # Check dead letter queue
        dead_letters = queue.get_dead_letters()
        assert len(dead_letters) == 1
        assert dead_letters[0]["job_id"] == "failing"
    
    def test_clear_dead_letters(self, queue):
        """Test clearing dead letter queue"""
        queue.enqueue({"job_id": "dl-1", "model": "test"})
        queue.dead_letter("dl-1", "test reason")
        
        assert queue.redis.zcard(queue._dead_letter_key) == 1
        
        count = queue.clear_dead_letters()
        
        assert count == 1
        assert queue.redis.zcard(queue._dead_letter_key) == 0


class TestRedisJobQueueStats:
    """Statistics Tests / 统计测试"""
    
    @pytest.fixture
    def queue(self):
        """Create queue with mock Redis"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import RedisJobQueue
            q = RedisJobQueue(host="localhost", port=6379, max_size=100)
            q._redis = mock_redis
            yield q
    
    def test_get_stats(self, queue):
        """Test queue statistics"""
        for i in range(5):
            queue.enqueue({
                "job_id": f"stats-{i}",
                "priority": 5,
                "bid_price": 0.5,
            })
        
        stats = queue.get_stats()
        
        assert stats.size == 5
        assert stats.max_size == 100
        assert stats.usage_percent == 5.0
    
    def test_health_check(self, queue):
        """Test health check"""
        health = queue.health_check()
        
        assert health["status"] == "healthy"
        assert "redis_version" in health


class TestRedisJobQueueFactory:
    """Factory Function Tests / 工厂函数测试"""
    
    def test_get_redis_queue_with_url(self):
        """Test creating queue from URL"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import get_redis_queue
            
            queue = get_redis_queue(url="redis://localhost:6379/0")
            
            assert queue._host == "localhost"
            assert queue._port == 6379
            assert queue._db == 0
    
    def test_get_redis_queue_with_kwargs(self):
        """Test creating queue from kwargs"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import get_redis_queue
            
            queue = get_redis_queue(
                host="my-redis",
                port=6380,
                db=1,
                password="secret"
            )
            
            assert queue._host == "my-redis"
            assert queue._port == 6380
            assert queue._db == 1


class TestRedisJobQueueEdgeCases:
    """Edge Case Tests / 边界情况测试"""
    
    @pytest.fixture
    def queue(self):
        """Create queue with mock Redis"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import RedisJobQueue
            q = RedisJobQueue(host="localhost", port=6379, max_size=100)
            q._redis = mock_redis
            yield q
    
    def test_queue_full_error(self):
        """Test queue full error - use small max_size"""
        with patch('redis.Redis') as mock_redis_cls:
            mock_redis = MockRedis()
            mock_redis_cls.return_value = mock_redis
            
            from src.services.queue.redis_queue import RedisJobQueue
            q = RedisJobQueue(host="localhost", port=6379, max_size=2)
            q._redis = mock_redis
            
            q.enqueue({"job_id": "full-1", "model": "test"})
            q.enqueue({"job_id": "full-2", "model": "test"})
            
            with pytest.raises(QueueFullError):
                q.enqueue({"job_id": "full-3", "model": "test"})
    
    def test_dequeue_empty_queue(self, queue):
        """Test dequeue from empty queue"""
        result = queue.dequeue()
        assert result is None
    
    def test_empty_job_data_error(self, queue):
        """Test empty job data raises error"""
        # Empty dict should fail (length 0)
        with pytest.raises(InvalidJobError):
            queue.enqueue({})
    
    def test_clear_queue(self, queue):
        """Test clearing queue"""
        for i in range(3):
            queue.enqueue({"job_id": f"clear-{i}", "model": "test"})
        
        count = queue.clear()
        
        assert count == 3
        assert queue.redis.zcard(queue._queue_key) == 0
