# Match Engine 架构文档

> DCM v3.2 | 去中心化计算市场匹配引擎

---

## 1. 概述

Match Engine 是 DCM 的核心撮合引擎，负责将 Job 与 Cluster 进行智能匹配。

### 核心职责

- **模型兼容性检查** - 确保 Job 需求与 Cluster 支持的模型匹配
- **容量管理** - 管理 Cluster 的并发和队列容量
- **智能调度** - 基于价格、延迟、负载等评分选择最优 Cluster
- **Pre-Lock 机制** - 防止高并发时的资源争抢

---

## 2. 匹配流程

### 2.1 完整匹配流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Match Job 流程                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  Job 提交
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 1: 获取候选 Clusters                                                       │
│                                                                             │
│   - 根据 Job.model_requirement 获取模型家族                                  │
│   - 从 OrderBook 获取该家族的所有 Clusters                                       │
│   - 如果没有指定模型，获取所有 Clusters                                          │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 2: Hard Filter (硬过滤)                                                 │
│                                                                             │
│   检查每个 Cluster 是否满足基本要求:                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐    │
│   │  ✓ 模型兼容性     - Cluster 是否支持该模型                              │    │
│   │  ✓ 容量检查       - available_capacity > 0                          │    │
│   │  ✓ 价格检查       - Cluster 价格 ≤ Job 报价                            │    │
│   │  ✓ 延迟检查       - Cluster 延迟 ≤ Job 最大延迟                         │    │
│   └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│   不满足任一条件的 Cluster 被过滤                                                │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 3: Scoring (评分排序)                                                   │
│                                                                             │
│   评分公式 (满分 1.0):                                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐    │
│   │  score = price_score × 0.30                                         │    │
│   │        + latency_score × 0.25                                       │    │
│   │        + load_score × 0.15                                          │    │
│   │        + reputation_score × 0.15                                    │    │
│   │        + compatibility_score × 0.15                                  │    │
│   └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│   按评分从高到低排序                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 4: 匹配决策                                                             │
│                                                                             │
│   job_tokens = input_tokens + output_tokens_limit                          │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐    │
│   │                                                                      │    │
│   │   for cluster in ranked_clusters:                                         │    │
│   │                                                                      │    │
│   │       ┌─────────────────────────────────────────────────────────┐   │    │
│   │       │  if available_capacity > 0                             │   │    │
│   │       │     AND available_queue >= job_tokens:                  │   │    │
│   │       │                                                          │   │    │
│   │       │     → 直接匹配 (pre_locked = False)                      │   │    │
│   │       │     → reserve(job_tokens)                               │   │    │
│   │       │     → return MatchResult(success=True)                   │   │    │
│   │       │                                                          │   │    │
│   │       ├─────────────────────────────────────────────────────────┤   │    │
│   │       │  elif available_capacity > 0:                             │   │    │
│   │       │                                                          │   │    │
│   │       │     → PreLock (pre_locked = True)                        │   │    │
│   │       │     → pre_lock_request(ttl_ms, tokens)                   │   │    │
│   │       │     → receive_ack()                                       │   │    │
│   │       │     → return MatchResult(success=True)                    │   │    │
│   │       │                                                          │   │    │
│   │       ├─────────────────────────────────────────────────────────┤   │    │
│   │       │  else:                                                     │   │    │
│   │       │                                                          │   │    │
│   │       │     → 无法匹配 (Cluster 已满)                                │   │    │
│   │       │     → 尝试下一个 Cluster                                     │   │    │
│   │       │                                                          │   │    │
│   │       └─────────────────────────────────────────────────────────┘   │    │
│   │                                                                      │    │
│   └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 5: 更新状态 & 返回结果                                                   │
│                                                                             │
│   - 更新 Job 状态: PENDING → MATCHED                                       │
│   - 创建 Match 记录                                                         │
│   - 从 OrderBook 移除 Job                                                  │
│   - 返回 MatchResult                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 匹配决策矩阵

| available_capacity | available_queue | job_tokens | 匹配方式 | pre_locked |
|-------------------|----------------|------------|----------|------------|
| > 0 | ≥ job_tokens | - | 直接匹配 | False |
| > 0 | < job_tokens | - | PreLock | True |
| = 0 | - | - | 无法匹配 | - |

---

## 3. 容量模型

### 3.1 容量层次结构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Cluster 容量模型                                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  max_concurrency: 最大并发数                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                                                                          │    │
│  │   reserved_jobs: 已预约但未执行的 Job 数                                    │    │
│  │   ┌─────────────────────────────────────────────────────────────────┐  │    │
│  │   │                                                                      │  │    │
│  │   │   active_jobs: 正在执行的 Job 数                                       │  │    │
│  │   │   ┌───────────────────────────────────────────────────────────┐ │ │  │    │
│  │   │   │                                                                   │ │ │  │    │
│  │   │   │   [执行中] [执行中] [执行中] [执行中]  ← max_concurrency = 4         │ │ │  │    │
│  │   │   │                                                                   │ │ │  │    │
│  │   │   └───────────────────────────────────────────────────────────┘ │ │  │    │
│  │   │                                                                      │  │    │
│  │   └─────────────────────────────────────────────────────────────────┘  │    │
│  │                                                                          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  available_capacity = max_concurrency - reserved_jobs - active_jobs        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 容量计算公式

```python
total_jobs = active_jobs + reserved_jobs + pre_locked_jobs

available_capacity = max(0, max_concurrency - total_jobs)

# 直接匹配条件
can_direct_match = available_capacity > 0 and available_queue >= job_tokens

# PreLock 条件
can_prelock = available_capacity > 0
```

### 3.3 容量状态

| 状态 | available_capacity | 说明 |
|------|-------------------|------|
| FREE | = max_concurrency | 完全空闲 |
| PARTIALLY_RESERVED | > 0 且 < max_concurrency | 部分占用 |
| FULLY_RESERVED | = 0 | 已满 |
| RUNNING | > 0 | 有 Job 正在执行 |

---

## 4. PreLock 机制

### 4.1 PreLock 流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            PreLock 流程                                     │
└─────────────────────────────────────────────────────────────────────────────┘

  场景: available_capacity > 0 但 available_queue < job_tokens

     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 1: Request PreLock                                                     │
│                                                                             │
│   pre_lock_service.request_pre_lock(                                         │
│       job_id,                                                               │
│       cluster,                                                                 │
│       ttl_ms=5000,       # 默认 5 秒过期                                    │
│       tokens=job_tokens  # 预留的 token 数量                                 │
│   )                                                                         │
│                                                                             │
│   - 创建 PRE_LOCK 类型的 ClusterLock                                             │
│   - pre_locked_jobs += 1                                                    │
│   - 预留 token 容量: available_queue -= tokens                               │
│   - 设置过期时间: expires_at = now + ttl_ms                                  │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 2: Receive Ack (Node Agent 确认)                                        │
│                                                                             │
│   pre_lock_service.receive_ack(job_id, cluster)                               │
│                                                                             │
│   - 检查是否有有效的 PRE_LOCK                                                 │
│   - 调用 cluster.confirm_pre_lock(job_id)                                      │
│       → 移除 PRE_LOCK，创建 HARD_LOCK                                       │
│       → pre_locked_jobs -= 1                                                │
│       → reserved_jobs += 1                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 3: 执行 Job                                                            │
│                                                                             │
│   match_engine.start_job_execution(job_id)                                  │
│                                                                             │
│   - reserved_jobs -= 1                                                     │
│   - active_jobs += 1                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 4: 完成/释放                                                           │
│                                                                             │
│   match_engine.complete_job(job_id)                                         │
│                                                                             │
│   - cluster.release_lock(job_id)                                               │
│       → 移除 HARD_LOCK                                                      │
│       → reserved_jobs -= 1 (如果是 HARD_LOCK)                               │
│       → active_jobs -= 1 (如果是 RUNNING)                                   │
│       → 释放 token 容量: available_queue += tokens                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 PreLock TTL 超时处理

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PreLock 超时处理                                     │
└─────────────────────────────────────────────────────────────────────────────┘

  Job 到达
     │
     ▼
┌───────────────────┐     TTL 有效      ┌───────────────────┐
│   PRE_LOCK        │ ───────────────► │   HARD_LOCK       │
│                   │                   │                   │
│   expires_at     │                   │   (已确认)        │
│   = now + ttl     │                   │                   │
└───────────────────┘                   └───────────────────┘
        │
        │ TTL 过期 (now > expires_at)
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ cleanup_cluster_expired(cluster)                                                  │
│                                                                             │
│   - 遍历所有过期的 PRE_LOCK                                                  │
│   - 移除 PRE_LOCK                                                          │
│   - pre_locked_jobs -= 1                                                    │
│   - 释放 token 容量: available_queue += tokens                             │
│   - Cluster 状态更新                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────┐
│   Cluster            │
│   释放容量         │
└───────────────────┘
```

---

## 5. Lock 类型

### 5.1 Lock 类型定义

| Lock 类型 | 说明 | 生命周期 |
|----------|------|----------|
| PRE_LOCK | 预锁定，等待确认 | ttl_ms 后自动过期 |
| HARD_LOCK | 硬锁定，已确认预约 | 直到 release |
| RUNNING | 运行中 | 直到完成 |

### 5.2 Lock 状态转换

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Lock 状态转换                                      │
└─────────────────────────────────────────────────────────────────────────────┘

      ┌──────────────────────────────────────────────────────────────────┐
      │                                                                  │
      │   pre_lock(job_id, ttl_ms)                                       │
      │                                                                  │
      ▼                                                                  │
┌─────────────┐          TTL 过期              ┌─────────────┐
│  PRE_LOCK   │ ─────────────────────────────► │   (清理)    │
│             │                                  │             │
│ expires_at  │         confirm_pre_lock       │             │
│ = now+ttl   │ ─────────────────────────────► │             │
└─────────────┘                                  └─────────────┘
                                                   │
                                                   ▼
                                            ┌─────────────┐
                                            │  HARD_LOCK  │
                                            │             │
                                            │ (已确认)    │
                                            └─────────────┘
                                                   │
                                                   ▼
                                            ┌─────────────┐
                                            │  start_     │
                                            │  running()  │
                                            └─────────────┘
                                                   │
                                                   ▼
                                            ┌─────────────┐
                                            │  RUNNING   │
                                            │             │
                                            │ 执行中...   │
                                            └─────────────┘
                                                   │
                                                   ▼
                                            ┌─────────────┐
                                            │  release_   │
                                            │  lock()     │
                                            └─────────────┘
                                                   │
                                                   ▼
                                            ┌─────────────┐
                                            │  (释放)     │
                                            │             │
                                            │ capacity++  │
                                            └─────────────┘
```

---

## 6. Job 生命周期

### 6.1 Job 状态转换

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Job 生命周期                                       │
└─────────────────────────────────────────────────────────────────────────────┘

  创建
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   ┌─────────┐    submit_job()     ┌─────────┐    match_job()     ┌─────┐ │
│   │ CREATED │ ──────────────────► │ PENDING │ ──────────────────► │MATCH│ │
│   └─────────┘                    └─────────┘                    │  ED  │ │
│                                                                      │     │ │
│                                         ┌──────────────────────────────┘     │ │
│                                         │                                    │ │
│                                         ▼                                    │ │
│                                   ┌──────────┐                               │ │
│                                   │PRE_LOCKED│                              │ │
│                                   └──────────┘                               │ │
│                                         │                                    │ │
│                                         ▼                                    │ │
│                                   ┌──────────┐                               │ │
│                                   │ RESERVED │ ◄── confirm_pre_lock()      │ │
│                                   └──────────┘                               │ │
│                                         │                                    │ │
│                                         ▼                                    │ │
│                                   ┌───────────┐                              │ │
│                                   │DISPATCHED │ ◄── dispatch_job()            │ │
│                                   └───────────┘                              │ │
│                                         │                                    │ │
│                                         ▼                                    │ │
│                                   ┌──────────┐                               │ │
│                                   │ RUNNING  │ ◄── start_job_execution()     │ │
│                                   └──────────┘                              │ │
│                                         │                                    │ │
│                         ┌───────────────┴───────────────┐                    │ │
│                         ▼                               ▼                    │ │
│                 ┌───────────┐                   ┌──────────┐                │ │
│                 │ COMPLETED │                   │  FAILED  │                │ │
│                 └───────────┘                   └──────────┘                │ │
│                         │                               │                    │ │
│                         ▼                               ▼                    │ │
│                 ┌───────────┐                   ┌──────────┐                │ │
│                 │ can_retry?│                   │ can_retry│                │ │
│                 │  (失败?)  │                   │  (失败?)  │                │ │
│                 └───────────┘                   └──────────┘                │ │
│                         │                               │                    │ │
│                         ▼                               ▼                    │ │
│                 ┌───────────┐                   ┌──────────┐                │ │
│                 │  (结束)   │                   │  重试    │                │ │
│                 └───────────┘                   └──────────┘                │ │
│                                                                     │       │ │
│                                                                     │       │ │
│                                                                     ▼       │ │
│                                                             ┌──────────┐    │ │
│                                                             │CANCELLED │    │ │
│                                                             └──────────┘    │ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 状态说明

| 状态 | 说明 | 可进行的操作 |
|------|------|-------------|
| CREATED | 已创建 | submit |
| PENDING | 等待匹配 | match |
| MATCHED | 已匹配 | dispatch |
| PRE_LOCKED | 预锁定中 | confirm |
| RESERVED | 已预约 | dispatch |
| DISPATCHED | 已分发 | start_execution |
| RUNNING | 执行中 | complete/fail |
| COMPLETED | 已完成 | - |
| FAILED | 失败 | retry/cancel |
| CANCELLED | 已取消 | - |

---

## 7. 数据结构

### 7.1 MatchEngineV2 核心属性

```python
class MatchEngineV2:
    def __init__(self):
        self.order_book: OrderBook          # 订单簿
        self.compatibility: Compatibility    # 兼容性服务
        self.hard_filter: HardFilter         # 硬过滤器
        self.scoring: Scoring                # 评分服务
        self.pre_lock: PreLockService        # PreLock 服务
        
        # 内部状态
        self._nodes: Dict[str, Node]         # Node 缓存
        self._clusters: Dict[str, Cluster]         # Cluster 缓存
        self._jobs: Dict[str, Job]           # Job 缓存
        self._matches: Dict[str, Match]      # Match 记录
        self._job_cluster: Dict[str, str]       # Job → Cluster 映射
        self._job_to_match: Dict[str, str]    # Job → Match 映射
```

### 7.2 Cluster 核心属性

```python
class CapacityInfo:
    max_concurrency: int     # 最大并发数
    active_jobs: int         # 正在执行的 Job 数
    reserved_jobs: int       # 已预约的 Job 数
    pre_locked_jobs: int    # 预锁定的 Job 数
    max_queue: int          # 最大队列容量 (tokens)
    available_queue: int    # 可用队列容量 (tokens)
    
    @property
    def available_capacity(self) -> int:
        return max(0, self.max_concurrency - self.total_jobs)

class Cluster:
    cluster_id: str
    node_id: str
    worker_id: str
    capacity: CapacityInfo
    model: ModelInfo
    pricing: PricingInfo
    performance: PerformanceInfo
    status: ClusterStatus
    job_sets: JobSet
    locks: List[ClusterLock]
```

### 7.3 MatchResult 返回结构

```python
class MatchResult:
    success: bool              # 是否成功
    pre_locked: bool           # 是否为 PreLock
    cluster: Optional[Cluster]       # 匹配的 Cluster
    job: Optional[Job]         # Job 对象
    score: Optional[float]    # 匹配评分
    pre_lock_expires_at: Optional[datetime]  # PreLock 过期时间
    reason: Optional[str]      # 失败原因
```

---

## 8. 配置参数

### 8.1 Job 配置 (job_config)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_output_tokens | 256 | 最大输出 token 数 |
| max_input_tokens | 128000 | 最大输入 token 数 |
| max_latency_ms | 30000 | 最大延迟 (ms) |
| min_latency_ms | 1000 | 最小延迟 (ms) |
| max_bid_price | 10.0 | 最大报价 |
| min_bid_price | 0.001 | 最小报价 |
| max_retries | 2 | 最大重试次数 |

### 8.2 PreLock 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| pre_lock_ttl_ms | 5000 | PreLock 默认 TTL (ms) |
| escrow_buffer | 1.1 | Escrow 缓冲倍数 |

---

## 9. 评分公式详解

### 9.1 各维度评分

```python
# 价格评分 (越便宜越好)
price_score = 1 - (cluster_price / job_bid_price)
price_score = max(0, min(1, price_score))

# 延迟评分 (越低越好)
latency_score = 1 - (cluster_latency / job_max_latency)
latency_score = max(0, min(1, latency_score))

# 负载评分 (负载低 = 分数高)
load_score = cluster.available_capacity / cluster.max_concurrency

# 声誉评分 (基于成功率)
reputation_score = cluster.avg_success_rate

# 兼容性评分
compatibility_score = 计算模型兼容性 (EXACT=1.0, FAMILY=0.8, COMPATIBLE=0.6)
```

### 9.2 综合评分

```python
total_score = (
    price_score * 0.30 +
    latency_score * 0.25 +
    load_score * 0.15 +
    reputation_score * 0.15 +
    compatibility_score * 0.15
)
```

---

## 10. 错误处理

### 10.1 MatchResult 失败原因

| reason | 说明 | 可能原因 |
|--------|------|----------|
| job_not_found | Job 不存在 | Job 未提交或已被移除 |
| no_available_clusters | 无可用 Cluster | 没有满足条件的 Cluster |
| no_clusters_passed_filter | Cluster 过滤失败 | 模型/价格/延迟不满足 |
| all_clusters_match_failed | 所有匹配失败 | Cluster 容量已满 |
| queue_reserve_failed | 队列预留失败 | available_queue 不足 |
| cluster_reserve_failed | Cluster 预约失败 | available_capacity 不足 |
| pre_lock_failed | PreLock 失败 | Cluster 已满 |

### 10.2 错误处理策略

```python
def match_job(self, job_id: str, pre_lock_ttl_ms: int = 5000) -> MatchResult:
    # 1. 参数验证
    job = self.get_job(job_id)
    if not job:
        return MatchResult(success=False, reason="job_not_found")
    
    # 2. 获取候选 Cluster
    candidate_clusters = self.order_book.get_clusters(family)
    if not candidate_clusters:
        return MatchResult(success=False, reason="no_available_clusters")
    
    # 3. 硬过滤
    filtered_clusters = self.hard_filter.filter_many(candidate_clusters, job)
    if not filtered_clusters:
        return MatchResult(success=False, reason="no_clusters_passed_filter")
    
    # 4. 评分排序
    ranked = self.scoring.rank_clusters(filtered_clusters, job)
    
    # 5. 尝试匹配 (按优先级)
    for cluster, score in ranked:
        if cluster.capacity.available_capacity > 0:
            # 尝试直接匹配或 PreLock
            ...
    
    # 6. 所有 Cluster 都失败
    return MatchResult(success=False, reason="all_clusters_match_failed")
```

---

## 11. 附录

### 11.1 术语表

| 术语 | 说明 |
|------|------|
| Job | 推理任务请求 |
| Cluster | GPU 算力单元 |
| Node | 计算节点 |
| PreLock | 预锁定机制 |
| OrderBook | 订单簿 |
| HardFilter | 硬过滤器 |
| Scoring | 评分函数 |
| Match | 匹配记录 |

### 11.2 相关文件

```
src/services/
├── match_engine_v2.py      # 匹配引擎核心
├── order_book.py           # 订单簿
├── hard_filter.py          # 硬过滤器
├── scoring.py              # 评分函数
├── compatibility.py        # 兼容性检查
└── pre_lock.py            # PreLock 服务

src/models/
├── job.py                  # Job 模型
├── cluster.py                 # Cluster 模型
├── node.py                 # Node 模型
└── match.py               # Match 模型
```

---

*文档版本: v3.2*
*最后更新: 2026-04-14*
