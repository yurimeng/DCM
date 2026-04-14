"""
Job Queue 单元测试
测试 JobQueueService 的基本功能
"""

import pytest
import time
import threading
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.services.queue.in_memory_queue import InMemoryJobQueue, reset_job_queue
from src.services.queue.job_queue import QueueFullError, InvalidJobError


class TestInMemoryJobQueue:
    """测试 InMemoryJobQueue"""
    
    def setup_method(self):
        """每个测试前重置队列"""
        reset_job_queue()
        self.queue = InMemoryJobQueue(max_size=100)
    
    def teardown_method(self):
        """每个测试后清空队列"""
        self.queue.clear()
    
    def _make_job(self, job_id: str, model: str = "qwen2.5:7b", 
                  bid_price: float = 0.001, priority: int = 0) -> dict:
        """创建测试用 Job 数据"""
        return {
            "job_id": job_id,
            "user_id": "user_test",
            "model": model,
            "input_tokens": 100,
            "output_tokens_limit": 500,
            "bid_price": bid_price,
            "max_latency": 60000,
            "priority": priority,
        }
    
    def test_enqueue_basic(self):
        """测试基本入队"""
        job = self._make_job("job_1")
        job_id = self.queue.enqueue(job)
        
        assert job_id == "job_1"
        assert self.queue.size() == 1
    
    def test_enqueue_multiple(self):
        """测试多次入队"""
        for i in range(5):
            job = self._make_job(f"job_{i}")
            self.queue.enqueue(job)
        
        assert self.queue.size() == 5
    
    def test_enqueue_duplicate(self):
        """测试重复入队 (允许重复 ID)"""
        job1 = self._make_job("job_1", bid_price=0.001)
        job2 = self._make_job("job_1", bid_price=0.002)  # 相同 ID
        
        self.queue.enqueue(job1)
        self.queue.enqueue(job2)  # 重复 ID - 会被视为不同的 Job
        
        # 当前实现允许重复，后续可以优化为更新
        assert self.queue.size() == 2
    
    def test_enqueue_full(self):
        """测试队列满"""
        small_queue = InMemoryJobQueue(max_size=2)
        
        small_queue.enqueue(self._make_job("job_1"))
        small_queue.enqueue(self._make_job("job_2"))
        
        with pytest.raises(QueueFullError):
            small_queue.enqueue(self._make_job("job_3"))
    
    def test_dequeue_basic(self):
        """测试基本出队"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.enqueue(self._make_job("job_2"))
        
        # FIFO: job_1 先出
        job = self.queue.dequeue()
        assert job["job_id"] == "job_1"
        assert self.queue.size() == 1
    
    def test_dequeue_empty(self):
        """测试空队列出队"""
        job = self.queue.dequeue(timeout=0.1)
        assert job is None
    
    def test_dequeue_priority(self):
        """测试优先级出队"""
        # 入队: job_1 (bid=0.001), job_2 (bid=0.003), job_3 (bid=0.002)
        self.queue.enqueue(self._make_job("job_1", bid_price=0.001))
        self.queue.enqueue(self._make_job("job_2", bid_price=0.003))
        self.queue.enqueue(self._make_job("job_3", bid_price=0.002))
        
        # 第一次出队: 应该先出 job_2 (bid_price 最高)
        job = self.queue.dequeue()
        assert job["job_id"] == "job_2"
    
    def test_dequeue_with_priority_field(self):
        """测试显式优先级字段"""
        # 入队: job_1 (priority=1), job_2 (priority=3), job_3 (priority=2)
        self.queue.enqueue(self._make_job("job_1", priority=1))
        self.queue.enqueue(self._make_job("job_2", priority=3))
        self.queue.enqueue(self._make_job("job_3", priority=2))
        
        # 第一次出队: 应该先出 job_2 (priority 最高)
        job = self.queue.dequeue()
        assert job["job_id"] == "job_2"
        
        # 第二次: job_3
        job = self.queue.dequeue()
        assert job["job_id"] == "job_3"
    
    def test_peek(self):
        """测试查看但不出队"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.enqueue(self._make_job("job_2"))
        
        jobs = self.queue.peek(2)
        assert len(jobs) == 2
        
        # 队列大小不变
        assert self.queue.size() == 2
    
    def test_acknowledge(self):
        """测试确认"""
        self.queue.enqueue(self._make_job("job_1"))
        job = self.queue.dequeue()
        
        result = self.queue.acknowledge(job["job_id"])
        assert result is True
        
        stats = self.queue.get_stats()
        assert stats.total_completed == 1
    
    def test_retry(self):
        """测试重试"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.dequeue()
        
        # 重新入队
        result = self.queue.retry("job_1")
        assert result is True
        assert self.queue.size() == 1
        
        # 再次出队
        job = self.queue.dequeue()
        assert job["job_id"] == "job_1"
    
    def test_retry_with_delay(self):
        """测试延迟重试"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.dequeue()
        
        # 延迟 1 秒重试
        self.queue.retry("job_1", delay=1.0)
        
        # 立即出队应该为空
        job = self.queue.dequeue(timeout=0.1)
        assert job is None
        
        # 等待 1.5 秒
        time.sleep(1.5)
        
        # 现在可以出队
        job = self.queue.dequeue()
        assert job["job_id"] == "job_1"
    
    def test_dead_letter(self):
        """测试死信"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.dequeue()
        
        result = self.queue.dead_letter("job_1", "timeout")
        assert result is True
        
        # 获取死信队列
        dl_jobs = self.queue.get_dead_letter_jobs()
        assert len(dl_jobs) == 1
        assert dl_jobs[0]["reason"] == "timeout"
    
    def test_requeue_dead_letter(self):
        """测试从死信重新入队"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.dequeue()
        self.queue.dead_letter("job_1", "timeout")
        
        # 重新入队
        result = self.queue.requeue_dead_letter("job_1")
        assert result is True
        
        # 死信队列应该为空
        assert len(self.queue.get_dead_letter_jobs()) == 0
        
        # 主队列应该有 1 个
        assert self.queue.size() == 1
    
    def test_stats(self):
        """测试统计"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.enqueue(self._make_job("job_2"))
        
        stats = self.queue.get_stats()
        assert stats.total_enqueued == 2
        assert stats.size == 2
    
    def test_clear(self):
        """测试清空队列"""
        self.queue.enqueue(self._make_job("job_1"))
        self.queue.enqueue(self._make_job("job_2"))
        
        self.queue.clear()
        
        assert self.queue.size() == 0
    
    def test_parse_family(self):
        """测试 model family 解析"""
        assert self.queue._parse_family("qwen2.5:7b") == "qwen"
        assert self.queue._parse_family("llama3:8b-instruct") == "llama"
        assert self.queue._parse_family("gemma4:e4b") == "gemma"
        assert self.queue._parse_family("") == "*"
    
    def test_concurrent_enqueue(self):
        """测试并发入队"""
        def worker(start: int, count: int):
            for i in range(count):
                self.queue.enqueue(self._make_job(f"job_{start + i}"))
        
        threads = [
            threading.Thread(target=worker, args=(0, 25)),
            threading.Thread(target=worker, args=(25, 25)),
            threading.Thread(target=worker, args=(50, 25)),
            threading.Thread(target=worker, args=(75, 25)),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert self.queue.size() == 100
    
    def test_concurrent_dequeue(self):
        """测试并发出队"""
        # 先填满队列
        for i in range(50):
            self.queue.enqueue(self._make_job(f"job_{i}"))
        
        results = []
        lock = threading.Lock()
        
        def worker():
            for _ in range(10):
                job = self.queue.dequeue()
                with lock:
                    if job:
                        results.append(job["job_id"])
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(results) == 50


class TestQueueIntegration:
    """测试队列集成 (与 Matching Service)"""
    
    def setup_method(self):
        reset_job_queue()
        from src.services.matching import MatchingService
        from src.services.queue import get_job_queue
        
        self.queue = get_job_queue()
        self.matching = MatchingService(queue=self.queue)
    
    def test_matching_with_queue(self):
        """测试撮合服务使用队列"""
        from src.models import Job, Node, NodeStatus
        from uuid import uuid4
        
        # 创建节点
        node = Node(
            node_id=f"node_{uuid4().hex[:8]}",
            user_id="user_test",
            gpu_type="Apple M5 Pro",
            gpu_vram_gb=0,
            vram_gb=0,  # 添加缺失字段
            gpu_qty=1,
            os_name="macOS",
            os_version="15.0",
            runtime="ollama",
            model="qwen2.5:7b",
            model_support=["qwen2.5:7b"],
            ask_price=0.001,
            status=NodeStatus.ONLINE,
            region="us-west",
            avg_latency=100,
            avg_success_rate=0.95,
            avg_quality_score=0.9,
        )
        self.matching.register_node(node)
        
        # 创建 Job
        job = Job(
            job_id=f"job_{uuid4().hex[:8]}",
            user_id="user_test",
            model_requirement="qwen2.5:7b",  # 使用 model_requirement
            input_tokens=100,
            output_tokens_limit=500,
            bid_price=0.001,
            max_latency=30000,  # 最大值限制
        )
        
        # 入队
        job_id = self.matching.add_job(job)
        assert job_id == job.job_id
        
        # 消费
        match = self.matching.consume_queue(timeout=1.0)
        assert match is not None
        assert match.node_id == node.node_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
