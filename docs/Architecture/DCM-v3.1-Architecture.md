"""
DCM v3.1 核心架构文档
=====================

> 版本: 3.1 (含 Pre-Lock 机制)
> 更新: 2026-04-13
> 状态: 已实现

---

## 一、层级关系（Execution Stack）

```
Level 1: SLOT        (Market Trading Unit)     ← 核心交易单元
Level 2: NODE        (Resource Container)       ← 资源容器
Level 3: WORKER      (Execution Scheduler)      ← 执行调度器
Level 4: RUNTIME     (Inference Engine)         ← 推理引擎
Level 5: MODEL       (LLM Weights)               ← 模型权重
```

---

## 二、核心实体定义

### 2.1 SLOT（交易单位）

```python
class Slot(BaseModel):
    slot_id: str                    # Slot 唯一 ID
    node_id: str                     # 所属节点
    worker_id: str                   # 所属 Worker
    
    # 模型与容量
    model: ModelInfo                 # 模型信息
    capacity: CapacityInfo           # 容量 (max_concurrency)
    
    # 定价与性能
    pricing: PricingInfo             # 定价
    performance: PerformanceInfo     # 性能
    
    # 状态与锁
    status: SlotStatus               # FREE/PRE_LOCKED/RESERVED/RUNNING
    locks: List[SlotLock]           # Pre-Lock 列表
    job_sets: JobSet                # reserved/running/queued
```

### 2.2 NODE（资源容器）

```python
class Node(BaseModel):
    node_id: str                     # 节点 ID
    slot_ids: List[str]             # 包含的 Slot IDs
    worker_ids: List[str]           # 包含的 Worker IDs
```

### 2.3 WORKER（执行调度器）

```python
class Worker(BaseModel):
    worker_id: str                    # Worker ID
    node_id: str                     # 所属节点
    runtime: RuntimeStatus            # IDLE/BUSY
    job_queue: List[str]             # Job 队列
```

### 2.4 RUNTIME（推理引擎）

```python
class Runtime(BaseModel):
    runtime_id: str                   # Runtime ID
    worker_id: str                   # 所属 Worker
    engine: str                      # vllm/ollama/tensorrt
    model: str                       # 模型名称
```

---

## 三、Slot 状态机 (v3.1)

```
FREE ─────────→ PRE_LOCKED ─────────→ RESERVED ─────────→ DISPATCHED ─────────→ RUNNING
  ↑                │                      │                      │                   │
  │                │                      │                      │                   │
  └────────────────┴──────────────────────┴──────────────────────┴──────────────────┘
                                               RELEASED
```

| 状态 | 描述 | 容量 |
|------|------|------|
| FREE | 可用 | 全部可用 |
| PRE_LOCKED | 预锁定中 | 部分占用 |
| PARTIALLY_RESERVED | 部分预约 | 部分占用 |
| FULLY_RESERVED | 全部预约 | 满 |
| RESERVED | 已预约 | 占用 |
| DISPATCHED | 已分发 | 占用 |
| RUNNING | 执行中 | 占用 |

---

## 四、Job 状态机 (v3.1)

```
PENDING → MATCHED → PRE_LOCKED → RESERVED → DISPATCHED → RUNNING → COMPLETED
              │                           ↓
              └──────────────────────→ FAILED
              └──────────────────────→ CANCELLED
```

---

## 五、Pre-Lock 机制 (v3.1 核心特性)

### 5.1 什么是 Pre-Lock？

Pre-Lock = Slot 已选定但未正式执行的资源占用状态

**目的**: 防止多 Job 抢占同一 Slot 导致的冲突

### 5.2 Pre-Lock 生命周期

```
Match Engine Select Slot
         ↓
SlotPreLock Request (TTL: 5000ms)
         ↓
SlotPreLock Ack / Reject
         ↓
Pre-Lock Confirmed → RESERVED
         ↓
Dispatch → Worker Queue
         ↓
Worker Execute
         ↓
SlotRelease → FREE
```

### 5.3 Lock 类型

| Lock 类型 | 描述 | TTL |
|----------|------|-----|
| PRE_LOCK | 临时预占 | 5000ms |
| HARD_LOCK | 已分配执行 | 无 |
| RUNNING | 正在执行 | 无 |

### 5.4 容量模型

```python
capacity = active_jobs + reserved_jobs + pre_locked_jobs ≤ max_concurrency
```

---

## 六、Job Match 逻辑

### Step 1: Hard Filter（硬过滤）

```python
def hard_filter(slot: Slot, job: Job) -> bool:
    # 1. 模型兼容性
    if compatibility_score(job.model, slot.model) <= 0:
        return False, "model_incompatible"
    
    # 2. Slot 状态
    if slot.status not in [FREE, PRE_LOCKED, PARTIALLY_RESERVED]:
        return False, "slot_not_available"
    
    # 3. 容量检查
    if slot.capacity.available_capacity <= 0:
        return False, "slot_at_capacity"
    
    # 4. 价格检查
    if slot.pricing.output_price > job.bid_price:
        return False, "output_price_too_high"
    
    # 5. 延迟检查
    if slot.performance.avg_latency_ms > job.max_latency:
        return False, "latency_too_high"
    
    return True, None
```

### Step 2: Compatibility Scoring（兼容性评分）

| 匹配类型 | 条件 | Score |
|----------|------|-------|
| EXACT | job.model == slot.model | 1.0 |
| FAMILY | 同家族 + 版本/Size 满足 | 0.8 |
| COMPATIBLE | 兼容模型 | 0.6 |
| CROSS_FAMILY | 跨家族 | 0.3 |
| INVALID | 不兼容 | 0.0 |

### Step 3: Scoring Function（综合评分）

```
Score = 0.30 * PriceScore 
      + 0.25 * LatencyScore 
      + 0.15 * LoadScore 
      + 0.15 * ReputationScore 
      + 0.15 * CompatibilityScore
```

### Step 4: Pre-Lock + Allocate

```python
def match_job(job_id) -> MatchResult:
    # 1. 获取候选 Slots
    slots = order_book.get_slots(family)
    
    # 2. Hard Filter
    filtered = hard_filter.filter_many(slots, job)
    
    # 3. Scoring 排序
    ranked = scoring.rank_slots(filtered, job)
    
    # 4. 尝试 Pre-Lock
    for slot, score in ranked:
        pre_lock_result = pre_lock.request(slot, job_id, ttl=5000)
        if pre_lock_result.success:
            # Ack 确认
            pre_lock.ack(slot, job_id)
            # 创建 Match
            return MatchResult(success=True, slot=slot)
    
    return MatchResult(success=False, reason="no_slot_available")
```

---

## 七、完整执行链路

```
JobCreate
    ↓
OrderBook Insert
    ↓
Match Engine
    ↓
Slot Discovery (by Family)
    ↓
Hard Filter (Compatibility + Capacity)
    ↓
Scoring (Price + Latency + Load + Reputation)
    ↓
Pre-Lock Request (TTL: 5000ms)
    ↓
Pre-Lock Ack
    ↓
Create Match
    ↓
Slot Reserve (HARD_LOCK)
    ↓
Dispatch to Node
    ↓
Node → Worker Queue
    ↓
Worker Execute
    ↓
Runtime Inference (Ollama/vLLM)
    ↓
Result Return
    ↓
SlotRelease
    ↓
Settlement
```

---

## 八、系统定义总结

| 组件 | 定义 | 职责 |
|------|------|------|
| SLOT | Economic Unit | 计算资源交易 |
| NODE | Resource Container | 资源聚合 |
| WORKER | Execution Scheduler | 任务调度 |
| RUNTIME | Inference Engine | 模型推理 |
| MODEL | AI Capability | AI 能力 |
| JOB | Demand Unit | 需求请求 |
| Pre-Lock | Short-Lived Reservation | 防冲突机制 |

---

## 九、一句话定义

> DCM v3.1 is a slot-based compute exchange with Pre-Lock mechanism that enables 
> multi-job concurrent execution through compatibility-aware scoring and 
> worker-queued runtime pipelines.
"""

# 文件位置: DCM/docs/Architecture/DCM-v3.1-Architecture.md
