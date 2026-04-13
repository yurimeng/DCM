---
title: F3-Matching 增强需求
type: function
module: Matching
created: 2026-04-13
updated: 2026-04-13
status: implemented
---

# F3-Matching 增强需求

## 1. 匹配条件

### 1.1 核心匹配条件（必须全部满足）

| 条件 | 字段 | 说明 |
|------|------|------|
| 模型匹配 | `job.model` in `node.model_support` | **最关键**，模型不一致直接拒绝 |
| 价格匹配 | `job.bid_price` <= `node.ask_price` | 买价 <= 卖价 |
| 延迟匹配 | `node.avg_latency` <= `job.max_latency` | 节点速度满足要求 |
| 节点状态 | `node.status` == `ONLINE` | 节点必须在线 |

### 1.2 质量匹配条件（可选）

| 条件 | 字段 | 说明 |
|------|------|------|
| 成功率 | `node.avg_success_rate` >= `job.min_success_rate` | 可选门槛 |
| 质量评分 | `node.avg_quality_score` >= `job.min_quality_score` | 可选门槛 |

---

## 2. Node 能力数据

### 2.1 基础信息
```python
class Node:
    node_id: str              # 节点唯一标识
    gpu_type: str            # GPU 类型
    vram_gb: int             # VRAM 大小
    model_support: List[str] # 支持的模型列表
    ask_price: float         # 报价 (USDC/1M tokens)
    region: str              # 地理区域
```

### 2.2 性能指标
```python
class Node:
    avg_latency: int         # 平均延迟 (ms)
    avg_success_rate: float   # 平均成功率 (0-1)
    avg_quality_score: float # 平均质量评分 (0-1)
```

---

## 3. Job 请求数据

### 3.1 基础信息
```python
class JobCreate:
    model: str               # 请求的模型
    input_tokens: int        # 输入 token 数
    output_tokens_limit: int # 输出 token 上限
    max_latency: int         # 最大延迟容忍 (ms)
    bid_price: float         # 报价 (USDC/1M tokens)
```

### 3.2 可选质量要求
```python
class JobCreate:
    min_success_rate: float   # 最低成功率要求 (0-1)
    min_quality_score: float  # 最低质量评分要求 (0-1)
```

---

## 4. 匹配算法

```
poll_node(node_id)
    │
    ▼
检查节点是否已有匹配 ──── 是 ──── 返回已有 Match
    │
    否
    ▼
获取节点信息
    │
    ▼
从 pending_jobs 排序 ──── bid_price 降序, created_at 升序
    │
    ▼
遍历 Jobs
    │
    ▼
检查 _can_match(job, node)
    │
    ├── 模型不匹配 ──→ 跳过，继续下一个
    ├── 价格不匹配 ──→ 跳过，继续下一个
    ├── 延迟不匹配 ──→ 跳过，继续下一个
    ├── 状态不在线 ──→ 跳过，继续下一个
    └── 全部通过 ────→ 创建 Match
```

---

## 5. 模型过滤示例

### 5.1 请求 qwen2.5:7b
```python
# Node 支持的模型
node.model_support = ["qwen2.5:7b", "llama3-8b"]

# Job 请求
job.model = "qwen2.5:7b"

# 匹配结果: ✓ 通过
```

### 5.2 请求 llama3-8b（Node 不支持）
```python
# Node 支持的模型
node.model_support = ["qwen2.5:7b"]

# Job 请求
job.model = "llama3-8b"

# 匹配结果: ✗ 不匹配
```

---

## 6. 实现清单

- [x] 模型匹配检查
- [x] 价格匹配检查
- [x] 延迟匹配检查
- [x] 节点状态检查
- [x] Node 成功率字段
- [x] Node 质量评分字段
- [ ] Job 最低成功率要求（可选）
- [ ] Job 最低质量评分要求（可选）

---

## 7. 相关文档

- [[F2-NodeAgent-Spec]] - Node Agent 规范
- [[F3-Matching]] - 基础撮合引擎
