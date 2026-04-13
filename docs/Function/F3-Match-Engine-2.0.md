---
title: F3 Match Engine 2.0
type: function
module: Matching
created: 2026-04-13
updated: 2026-04-13
status: draft
priority: P0
sprint: 8
---

# F3 Match Engine 2.0

## 概述

Slot-based 计算交易所，支持层级模型兼容性匹配。

## 核心对象

| 对象 | 描述 |
|------|------|
| **Slot** | 执行容量单元（Supply） |
| **Job** | 需求订单（Demand） |
| **Node** | Slot 容器 |
| **Worker** | 运行时执行器 |

## 架构

```
Node
 └─ Worker
      └─ Slot
           └─ Model
```

## 功能清单

- [ ] F3.1 Slot 数据结构
- [ ] F3.2 Order Book（按 Model Family 分桶）
- [ ] F3.3 Hard Filter（硬过滤条件）
- [ ] F3.4 Compatibility Matrix（兼容性矩阵）
- [ ] F3.5 Scoring Function（评分函数）
- [ ] F3.6 Slot Lifecycle（生命周期管理）
- [ ] F3.7 Slot Reservation & Release

---

# F3.1 Slot 数据结构

## Slot Schema

```python
class Slot(BaseModel):
    """Slot 执行容量单元"""
    slot_id: str
    node_id: str
    worker_id: str
    
    model: ModelInfo  # 模型信息
    capacity: CapacityInfo  # 容量信息
    pricing: PricingInfo  # 定价信息
    performance: PerformanceInfo  # 性能信息
    status: SlotStatus = SlotStatus.FREE

class ModelInfo(BaseModel):
    """模型信息"""
    family: str  # 模型族
    name: str  # 模型名

class CapacityInfo(BaseModel):
    """容量信息"""
    max_concurrency: int = 1
    current_load: int = 0
    max_tokens_per_sec: int = 100
    context_window: int = 4096

class PricingInfo(BaseModel):
    """定价信息"""
    input_price: float  # 输入 token 单价
    output_price: float  # 输出 token 单价

class PerformanceInfo(BaseModel):
    """性能信息"""
    avg_latency_ms: int
    success_rate: float = 0.95

class SlotStatus(str, Enum):
    FREE = "free"
    RESERVED = "reserved"
    RUNNING = "running"
    RELEASED = "released"
```

## Slot Lifecycle

```
FREE → RESERVED → RUNNING → RELEASED → FREE
```

---

# F3.2 Order Book

## 按 Model Family 分桶

```python
OrderBook = {
    "qwen": {
        "job_bids": [],  # 按 price 降序
        "slot_asks": [], # 按 price 升序
    },
    "llama": {...},
    "gemma": {...},
    "*": {...}  # 通用（不指定模型）
}
```

## 匹配规则

1. 先按 Model Family 分桶
2. 在桶内进行撮合
3. 通用 Job 可匹配任意桶

---

# F3.3 Hard Filter

## 过滤条件

```python
def hard_filter(slot: Slot, job: Job) -> bool:
    """硬过滤条件（必须全部满足）"""
    
    # 1. Slot 状态必须是 FREE
    if slot.status != SlotStatus.FREE:
        return False
    
    # 2. 容量检查
    if slot.capacity.current_load >= slot.capacity.max_concurrency:
        return False
    
    # 3. 价格检查
    if slot.pricing.input_price > job.pricing_bid.max_input_price:
        return False
    if slot.pricing.output_price > job.pricing_bid.max_output_price:
        return False
    
    # 4. 延迟检查
    if slot.performance.avg_latency_ms > job.constraints.max_latency_ms:
        return False
    
    # 5. 区域检查（可选）
    if job.constraints.region and slot.region != job.constraints.region:
        return False
    
    return True
```

---

# F3.4 Compatibility Matrix

## 兼容性评分

| 匹配类型 | 条件 | Score |
|----------|------|-------|
| Exact Match | `job.name == slot.name` | 1.0 |
| Family Match | `job.family == slot.family` 且 name 不同 | 0.8 |
| Compatible | 兼容模型（如 qwen2 → qwen3） | 0.6 |
| Cross Family | 跨族降级 | 0.3 |
| No Match | 不兼容 | 0 (过滤) |

## 兼容性判断

```python
def get_compatibility(job: Job, slot: Slot) -> float:
    """获取兼容性评分"""
    
    job_model = job.model_requirement
    slot_model = slot.model
    
    # Exact Match
    if job_model.name and job_model.name == slot_model.name:
        return 1.0
    
    # Family Match
    if job_model.family and job_model.family == slot_model.family:
        return 0.8
    
    # 通用任务（无 model 要求）
    if not job_model.name and not job_model.family:
        return 1.0  # 通用任务可匹配任何 slot
    
    return 0.0  # No Match
```

---

# F3.5 Scoring Function

## 综合评分

```
Score = 0.30 * PriceScore 
      + 0.25 * LatencyScore 
      + 0.15 * LoadScore 
      + 0.15 * ReputationScore 
      + 0.15 * CompatibilityScore
```

## 各维度评分

```python
def calculate_score(slot: Slot, job: Job) -> float:
    """计算综合评分"""
    
    # Price Score (越低越好)
    price_score = 1 - (slot.pricing.output_price / job.pricing_bid.max_output_price)
    
    # Latency Score (越低越好)
    latency_score = 1 - (slot.performance.avg_latency_ms / job.constraints.max_latency_ms)
    
    # Load Score (剩余容量越多越好)
    load_score = 1 - (slot.capacity.current_load / slot.capacity.max_concurrency)
    
    # Reputation Score
    reputation_score = slot.performance.success_rate
    
    # Compatibility Score
    compatibility_score = get_compatibility(job, slot)
    
    # 综合评分
    score = (
        0.30 * price_score +
        0.25 * latency_score +
        0.15 * load_score +
        0.15 * reputation_score +
        0.15 * compatibility_score
    )
    
    return score
```

---

# F3.6 Slot Lifecycle

## 状态流转

```
FREE ────→ RESERVED ────→ RUNNING ────→ RELEASED ───→ FREE
 │              │              │
 └──────────────┴──────────────┴──→ FAILED
```

## 状态定义

| 状态 | 描述 |
|------|------|
| FREE | 可用，等待匹配 |
| RESERVED | 已被 Job 预约 |
| RUNNING | 正在执行 Job |
| RELEASED | 执行完成，释放资源 |
| FAILED | 执行失败 |

---

# F3.7 Slot Reservation & Release

## Reservation

```python
def reserve_slot(slot_id: str, job_id: str) -> bool:
    """预约 Slot"""
    slot = get_slot(slot_id)
    
    if slot.status != SlotStatus.FREE:
        return False
    
    if slot.capacity.current_load >= slot.capacity.max_concurrency:
        return False
    
    # 更新状态
    slot.status = SlotStatus.RESERVED
    slot.current_job_id = job_id
    slot.capacity.current_load += 1
    
    return True
```

## Release

```python
def release_slot(slot_id: str, job_id: str) -> bool:
    """释放 Slot"""
    slot = get_slot(slot_id)
    
    if slot.current_job_id != job_id:
        return False
    
    # 更新状态
    slot.status = SlotStatus.RELEASED
    slot.current_job_id = None
    slot.capacity.current_load -= 1
    
    # 延迟重置为 FREE
    schedule_reset_to_free(slot_id, delay_ms=1000)
    
    return True
```

---

# 实现检查点

- [ ] CP-0024: F3.1 Slot 数据结构创建
- [ ] CP-0025: F3.2 Order Book 实现
- [ ] CP-0026: F3.3 Hard Filter 实现
- [ ] CP-0027: F3.4 Compatibility Matrix 实现
- [ ] CP-0028: F3.5 Scoring Function 实现
- [ ] CP-0029: F3.6-7 Slot Lifecycle 实现
- [ ] CP-0030: E2E 测试
