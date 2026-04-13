"""
F3 Match Engine 2.0 规范
=======================

> 版本: 3.1 (含 Pre-Lock 机制)
> 状态: 已实现
> 更新: 2026-04-13

---

## 一、概述

Slot-based 计算交易所，支持层级模型兼容性匹配和 Multi-Job 并发执行。

## 二、核心对象

| 对象 | 描述 |
|------|------|
| **Slot** | 执行容量单元（Supply） |
| **Job** | 需求订单（Demand） |
| **Node** | Slot 容器 |
| **Worker** | 运行时执行器 |
| **PreLock** | 资源预占机制 |

## 三、架构

```
Node
 └─ Worker
      └─ Slot
           └─ Model
```

## 四、功能清单

- [x] F3.1 Slot 数据结构
- [x] F3.2 Order Book（按 Model Family 分桶）
- [x] F3.3 Hard Filter（硬过滤条件）
- [x] F3.4 Compatibility Matrix（兼容性矩阵）
- [x] F3.5 Scoring Function（评分函数）
- [x] F3.6 Slot Lifecycle（生命周期管理）
- [x] F3.7 Slot Reservation & Release
- [x] **F3.8 Pre-Lock 机制**

---

# F3.1 Slot 数据结构

## Slot Schema

```python
class SlotStatus(str, Enum):
    FREE = "free"
    PRE_LOCKED = "pre_locked"
    PARTIALLY_RESERVED = "partially_reserved"
    FULLY_RESERVED = "fully_reserved"
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    RELEASED = "released"
    FAILED = "failed"

class CapacityInfo(BaseModel):
    max_concurrency: int = 1
    active_jobs: int = 0
    reserved_jobs: int = 0
    pre_locked_jobs: int = 0
    
    @property
    def available_capacity(self) -> int:
        return max(0, self.max_concurrency - 
                   self.active_jobs - 
                   self.reserved_jobs - 
                   self.pre_locked_jobs)
```

## Slot Lifecycle (v3.1)

```
FREE ───→ PRE_LOCKED ───→ RESERVED ───→ DISPATCHED ───→ RUNNING
  ↑          │               │              │               │
  │          │               │              │               │
  └──────────┴───────────────┴───────────────┴───────────────┘
                                RELEASED
```

---

# F3.2 Order Book

## 按 Model Family 分桶

```python
OrderBook = {
    "qwen": {
        "jobs": [],
        "slots": [],
    },
    "llama": {...},
    "*": {...}  # 通用
}
```

---

# F3.3 Hard Filter (v3.1)

```python
def hard_filter(slot: Slot, job: Job) -> tuple[bool, str]:
    # 1. 模型兼容性
    if compatibility_score <= 0:
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

---

# F3.4 Compatibility Matrix

## 兼容性评分

| 匹配类型 | 条件 | Score |
|----------|------|-------|
| EXACT | job.model == slot.model | 1.0 |
| FAMILY | 同家族 + 版本/Size 满足 | 0.8 |
| COMPATIBLE | 兼容模型 | 0.6 |
| CROSS_FAMILY | 跨家族 | 0.3 |
| INVALID | 不兼容 | 0.0 |

## 版本覆盖规则

```
4.0 → 3.5 → 3.0 → 2.5 → 2.0 (可降级)
70b → 14b → 7b → 2b (只能大服务小)
```

---

# F3.5 Scoring Function

```
Score = 0.30 * PriceScore 
      + 0.25 * LatencyScore 
      + 0.15 * LoadScore 
      + 0.15 * ReputationScore 
      + 0.15 * CompatibilityScore
```

---

# F3.6 Slot Lifecycle

## 状态定义

| 状态 | 描述 |
|------|------|
| FREE | 可用，等待匹配 |
| PRE_LOCKED | 预锁定中 |
| PARTIALLY_RESERVED | 部分预约 |
| FULLY_RESERVED | 满 |
| RESERVED | 已预约 |
| DISPATCHED | 已分发 |
| RUNNING | 执行中 |
| RELEASED | 已释放 |

---

# F3.7 Reservation & Release

```python
def reserve(slot: Slot, job_id: str) -> bool:
    if not slot.is_available():
        return False
    slot.pre_lock(job_id, ttl_ms=5000)
    return True

def release(slot: Slot, job_id: str) -> bool:
    return slot.finish_job(job_id)
```

---

# F3.8 Pre-Lock 机制 (v3.1 新增)

## Pre-Lock 请求

```python
def pre_lock(slot: Slot, job_id: str, ttl_ms: int = 5000) -> bool:
    """创建 Pre-Lock"""
    if slot.capacity.available_capacity <= 0:
        return False
    # 创建 PRE_LOCK 类型的 SlotLock
    return True
```

## Pre-Lock Ack

```python
def confirm_pre_lock(slot: Slot, job_id: str) -> bool:
    """确认 Pre-Lock 转换为 HARD_LOCK"""
    # 移除 PRE_LOCK，添加 HARD_LOCK
    # 更新 capacity.reserved_jobs += 1
    return True
```

## Lock 类型

| 类型 | TTL | 说明 |
|------|-----|------|
| PRE_LOCK | 5000ms | 临时预占 |
| HARD_LOCK | 无 | 已确认预约 |
| RUNNING | 无 | 执行中 |

---

# 实现检查点

- [x] CP-0024: F3.1 Slot 数据结构创建
- [x] CP-0025: F3.2 Order Book 实现
- [x] CP-0026: F3.3 Hard Filter 实现
- [x] CP-0027: F3.4 Compatibility Matrix 实现
- [x] CP-0028: F3.5 Scoring Function 实现
- [x] CP-0029: F3.6-7 Slot Lifecycle 实现
- [x] CP-0030: E2E 测试
- [x] CP-0031: F3.8 Pre-Lock 机制

---

## 相关文档

- [[DCM-v3.1-Architecture]] - 核心架构
- [[DCM-v3.1-PreLock-Mechanism]] - Pre-Lock 机制
- [[TEST-REPORT-2026-04-13]] - 测试报告
"""

# 文件位置: DCM/docs/Function/F3-Match-Engine-2.0.md
