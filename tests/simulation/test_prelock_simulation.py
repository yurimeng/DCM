"""
Pre-Lock 模拟测试 - DCM v3.2

测试场景:
1. 每 3 秒创建 5 个 job
2. Node 有固定 max_queue 容量 (如 300 tokens)
3. 每个 job 需要 tokens = input_tokens + output_tokens_limit
4. 当超过容量时触发 pre_lock 拒绝
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import List

# 导入 DCM 模块
import sys
sys.path.insert(0, '/Users/yurimeng/Code/Platform/DCM')

from src.models.node import Node, NodeStatus, QueueInfo
from src.models.slot import Slot, SlotStatus, ModelInfo, PricingInfo, PerformanceInfo, CapacityInfo
from src.models.job import Job, JobStatus
from src.services.pre_lock import PreLockService, PreLockResult, PreLockStatus


class SimulationStats:
    """模拟统计"""
    def __init__(self):
        self.jobs_created = 0
        self.pre_lock_success = 0
        self.pre_lock_rejected = 0
        self.pre_lock_expired = 0
        self.queue_reserved = 0
        self.queue_released = 0
    
    def print(self):
        print(f"\n{'='*60}")
        print(f"📊 模拟统计")
        print(f"{'='*60}")
        print(f"  Jobs 创建: {self.jobs_created}")
        print(f"  Pre-Lock 成功: {self.pre_lock_success}")
        print(f"  Pre-Lock 拒绝: {self.pre_lock_rejected}")
        print(f"  Pre-Lock 过期: {self.pre_lock_expired}")
        print(f"  Queue 预留: {self.queue_reserved}")
        print(f"  Queue 释放: {self.queue_released}")


def create_test_node(slot_count: int = 2, max_queue: int = 300, max_concurrency: int = 5) -> Node:
    """创建测试 Node (DCM v3.2)
    
    runtime 和 model 可以为空，测试时使用默认值
    max_concurrency: 允许的最大并发 Pre-Lock 数
    """
    # 创建 slots
    slots = []
    for i in range(slot_count):
        slot = Slot(
            slot_id=f"slot_{i}",
            node_id="test_node",
            worker_id="worker_1",
            model=ModelInfo(family="qwen", name="qwen2.5:7b"),
            pricing=PricingInfo(input_price=0.1, output_price=0.3),
            performance=PerformanceInfo(avg_latency_ms=1000),
            status=SlotStatus.FREE,
        )
        
        # 设置 Queue 容量 (DCM v3.2)
        slot.capacity.max_queue = max_queue
        slot.capacity.available_queue = max_queue
        slot.capacity.max_concurrency = max_concurrency  # 允许更多并发
        
        slots.append(slot)
    
    # 创建 Node (DCM v3.2: runtime/model 可以为空)
    node = Node(
        node_id="test_node",
        gpu_type="apple_m5_pro",
        vram_gb=24,
        runtime="ollama",  # 测试时设置默认值
        model="qwen2.5:7b",  # 测试时设置默认值
        ask_price=0.1,
        avg_latency=1000,
        region="us-west",
        gpu_count=1,
    )
    
    # 设置 slot_ids (DCM v3.2)
    node.slot_ids = [s.slot_id for s in slots]
    
    # 存储 slots 引用 (测试用)
    node._test_slots = slots
    
    node.status = NodeStatus.ONLINE
    
    # 设置 Node Queue 容量 (DCM v3.2)
    node.queue_info = QueueInfo(max_queue=max_queue * slot_count, available_queue=max_queue * slot_count)
    
    return node


def get_slots(node: Node) -> list:
    """获取 Node 的 Slots"""
    return getattr(node, '_test_slots', [])


def create_test_job(job_id: str, input_tokens: int, output_tokens_limit: int) -> Job:
    """创建测试 Job"""
    return Job(
        job_id=job_id,
        model_requirement="qwen2.5:7b",
        input_tokens=input_tokens,
        output_tokens_limit=output_tokens_limit,
        max_latency=5000,
        bid_price=0.1,
    )


def print_slot_status(slots: list):
    """打印 Slot 状态"""
    print(f"\n  Slot 状态:")
    for slot in slots:
        print(f"    {slot.slot_id}: "
              f"jobs={slot.capacity.total_jobs}/{slot.capacity.max_concurrency}, "
              f"queue={slot.capacity.available_queue}/{slot.capacity.max_queue}, "
              f"locks={[f'{l.job_id}:{l.lock_type.value}' for l in slot.locks]}")


def print_node_queue(queue_info: QueueInfo):
    """打印 Node Queue 状态"""
    print(f"  Node Queue: {queue_info.available_queue}/{queue_info.max_queue}")


async def simulate_pre_lock_test():
    """模拟 Pre-Lock 测试"""
    
    print("\n" + "="*60)
    print("🔬 Pre-Lock 模拟测试 - DCM v3.2")
    print("="*60)
    
    # 配置
    MAX_QUEUE_PER_SLOT = 300  # 每个 Slot 最大 Queue
    JOB_INTERVAL = 3  # 每 3 秒创建 jobs
    JOBS_PER_INTERVAL = 5  # 每次创建 5 个 jobs
    JOB_TOKENS = 100  # 每个 Job 的 token 数量 (input + output)
    
    stats = SimulationStats()
    
    # 创建 Node 和 PreLockService
    node = create_test_node(slot_count=2, max_queue=MAX_QUEUE_PER_SLOT, max_concurrency=10)
    slots = get_slots(node)  # 获取 slots 引用
    pre_lock_service = PreLockService(default_ttl_ms=5000)  # 5秒 TTL
    
    # 设置回调
    def on_confirmed(job_id: str, slot_id: str):
        stats.pre_lock_success += 1
        print(f"  ✓ Pre-Lock confirmed: job={job_id}, slot={slot_id}")
    
    def on_rejected(job_id: str, slot_id: str, reason: str):
        stats.pre_lock_rejected += 1
        print(f"  ✗ Pre-Lock rejected: job={job_id}, slot={slot_id}, reason={reason}")
    
    def on_expired(job_id: str, slot_id: str):
        stats.pre_lock_expired += 1
        print(f"  ⏰ Pre-Lock expired: job={job_id}, slot={slot_id}")
    
    pre_lock_service.set_callbacks(
        on_confirmed=on_confirmed,
        on_rejected=on_rejected,
        on_expired=on_expired,
    )
    
    print(f"\n📋 配置:")
    print(f"  每 Slot 最大 Queue: {MAX_QUEUE_PER_SLOT} tokens")
    print(f"  每 Job 需要: {JOB_TOKENS} tokens (input + output)")
    print(f"  每 {JOB_INTERVAL} 秒创建: {JOBS_PER_INTERVAL} 个 jobs")
    print(f"  Node 总容量: {MAX_QUEUE_PER_SLOT * 2} tokens (2 slots)")
    
    print(f"\n🔄 开始模拟...")
    print(f"  预期: 约 {MAX_QUEUE_PER_SLOT // JOB_TOKENS} 个 Job 后开始拒绝")
    
    for round_num in range(1, 6):  # 运行 5 轮
        print(f"\n{'='*60}")
        print(f"📦 第 {round_num} 轮 - {datetime.now().strftime('%H:%M:%S')}")
        print("="*60)
        
        # 创建 5 个 jobs
        jobs = []
        for i in range(JOBS_PER_INTERVAL):
            job_id = f"job_{round_num}_{i}"
            job = create_test_job(job_id, input_tokens=50, output_tokens_limit=50)
            jobs.append(job)
            stats.jobs_created += 1
            print(f"  [创建] {job_id}: {job.input_tokens + job.output_tokens_limit} tokens")
        
        print(f"\n  Node 初始状态:")
        print_node_queue(node.queue_info)
        print_slot_status(get_slots(node))
        
        # 尝试为每个 Job 请求 Pre-Lock
        print(f"\n  尝试 Pre-Lock:")
        for job in jobs:
            job_tokens = job.input_tokens + job.output_tokens_limit
            
            # 找一个可用的 Slot (检查 queue 容量)
            matched_slot = None
            for slot in slots:
                # DCM v3.2: 检查 queue 容量
                if slot.capacity.available_queue >= job_tokens:
                    matched_slot = slot
                    break
            
            if not matched_slot:
                print(f"    ✗ {job.job_id}: queue 容量不足 (需要 {job_tokens})")
                stats.pre_lock_rejected += 1
                continue
            
            # 请求 Pre-Lock
            result = pre_lock_service.request_pre_lock(
                job_id=job.job_id,
                slot=matched_slot,
                ttl_ms=5000,
                tokens=job_tokens,
            )
            
            if result.success:
                print(f"    ✓ {job.job_id} → {result.slot_id} (tokens={job_tokens}, expires={result.expires_at})")
                stats.queue_reserved += job_tokens
            else:
                print(f"    ✗ {job.job_id}: {result.reason}")
                if result.reason == "capacity_full":
                    stats.queue_reserved += job_tokens  # 尝试预留
                stats.pre_lock_rejected += 1
        
        print(f"\n  Node 最终状态:")
        print_node_queue(node.queue_info)
        print_slot_status(get_slots(node))
        
        # 模拟 Ack (前几个)
        pending_count = len(pre_lock_service._pending_requests)
        print(f"\n  等待 Ack 的请求: {pending_count}")
        
        if pending_count > 0:
            # 模拟部分 Ack
            ack_count = min(2, pending_count)
            for i, (job_id, request) in enumerate(list(pre_lock_service._pending_requests.items())[:ack_count]):
                slot = next((s for s in get_slots(node) if s.slot_id == request.slot_id), None)
                if slot:
                    result = pre_lock_service.receive_ack(job_id, slot)
                    print(f"    Ack: {job_id} → {result.status.value}")
        
        # 等待下一轮
        if round_num < 5:
            print(f"\n  ⏳ 等待 {JOB_INTERVAL} 秒...")
            await asyncio.sleep(JOB_INTERVAL)
    
    # 最终统计
    stats.print()
    
    # 打印最终状态
    print(f"\n📌 最终 Node 状态:")
    print_node_queue(node.queue_info)
    print_slot_status(get_slots(node))
    
    return stats


async def simulate_over_capacity():
    """模拟超过容量的场景"""
    print("\n\n" + "="*60)
    print("🔬 容量超限测试 - DCM v3.2")
    print("="*60)
    
    MAX_QUEUE = 100  # 很小容量
    JOB_TOKENS = 50  # 每个 Job 需要 50 tokens
    
    node = create_test_node(slot_count=1, max_queue=MAX_QUEUE, max_concurrency=10)
    slots = get_slots(node)
    slot = slots[0]
    pre_lock_service = PreLockService(default_ttl_ms=3000)
    
    print(f"\n📋 配置:")
    print(f"  Slot Queue 容量: {MAX_QUEUE} tokens")
    print(f"  每个 Job: {JOB_TOKENS} tokens")
    print(f"  预期: {MAX_QUEUE // JOB_TOKENS} 个 Job 后开始拒绝")
    
    # 快速创建 10 个 jobs
    print(f"\n🚀 快速创建 10 个 Jobs:")
    for i in range(10):
        job_id = f"burst_job_{i}"
        job_tokens = JOB_TOKENS  # 使用固定值
        
        result = pre_lock_service.request_pre_lock(
            job_id=job_id,
            slot=slot,
            tokens=job_tokens,
        )
        
        status = "✓" if result.success else "✗"
        print(f"  {status} {job_id}: {result.status.value if not result.success else f'queued, {slot.capacity.available_queue}/{slot.capacity.max_queue}'}")
    
    print(f"\n📊 最终状态:")
    print(f"  Queue: {slot.capacity.available_queue}/{slot.capacity.max_queue}")
    print(f"  Pending requests: {len(pre_lock_service._pending_requests)}")


async def simulate_queue_release():
    """模拟 Queue 释放 - DCM v3.2 优化版"""
    print("\n\n" + "="*60)
    print("🔬 Queue 释放测试 - DCM v3.2 优化")
    print("="*60)
    
    MAX_QUEUE = 150
    JOB_TOKENS = 50
    
    node = create_test_node(slot_count=1, max_queue=MAX_QUEUE, max_concurrency=10)
    slots = get_slots(node)
    slot = slots[0]
    pre_lock_service = PreLockService(default_ttl_ms=2000)  # 2秒 TTL 便于测试
    
    print(f"\n📋 配置: Slot Queue = {MAX_QUEUE}, 每 Job = {JOB_TOKENS} tokens, TTL = 2秒")
    
    # 创建 3 个 jobs
    print(f"\n🚀 创建 3 个 Jobs:")
    job_ids = []
    for i in range(3):
        job_id = f"release_job_{i}"
        job_ids.append(job_id)
        
        result = pre_lock_service.request_pre_lock(
            job_id=job_id,
            slot=slot,
            tokens=JOB_TOKENS,
        )
        print(f"  ✓ {job_id}: queue={slot.capacity.available_queue}/{slot.capacity.max_queue}")
    
    print(f"\n⏰ 等待 2.5 秒让 Pre-Locks 过期...")
    await asyncio.sleep(2.5)
    
    # 调用优化后的清理方法 (DCM v3.2)
    print(f"\n🧹 调用 cleanup_expired_pre_lock():")
    expired = pre_lock_service.check_and_cleanup_expired(slot)
    print(f"  清理了 {len(expired)} 个过期 Pre-Locks: {expired}")
    
    print(f"\n📊 清理后状态:")
    print(f"  Queue: {slot.capacity.available_queue}/{slot.capacity.max_queue}")
    print(f"  Pending requests: {len(pre_lock_service._pending_requests)}")
    print(f"  Locks: {[f'{l.job_id}:{l.lock_type.value}' for l in slot.locks]}")
    
    # 再创建 2 个
    print(f"\n🚀 再创建 2 个 Jobs:")
    for i in range(2):
        job_id = f"new_job_{i}"
        
        result = pre_lock_service.request_pre_lock(
            job_id=job_id,
            slot=slot,
            tokens=JOB_TOKENS,
        )
        
        status = "✓" if result.success else "✗"
        reason = f"({result.reason})" if not result.success else f"(queue={slot.capacity.available_queue})"
        print(f"  {status} {job_id}: {reason}")
    
    print(f"\n📊 最终状态:")
    print(f"  Queue: {slot.capacity.available_queue}/{slot.capacity.max_queue}")
    print(f"  Total jobs: {slot.capacity.total_jobs}")


async def main():
    """主函数"""
    print("\n" + "="*70)
    print("🧪 DCM v3.2 Pre-Lock 模拟测试")
    print("="*70)
    
    # 测试 1: 常规 Pre-Lock
    await simulate_pre_lock_test()
    
    # 测试 2: 容量超限
    await simulate_over_capacity()
    
    # 测试 3: Queue 释放
    await simulate_queue_release()
    
    print("\n" + "="*70)
    print("✅ 所有测试完成")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())