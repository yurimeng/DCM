# DCM 项目概览

> **Decentralized Compute Market** - 去中心化 AI 推理市场
> 
> **版本**: v3.2 | **状态**: MVP (Production Ready)

---

## 📁 目录结构

```
DCM/
├── src/                          # 主源代码
│   ├── api/                      # API 端点
│   │   ├── jobs.py              # Job 提交与查询
│   │   ├── nodes.py             # Node 注册与管理
│   │   ├── users.py             # 用户管理
│   │   ├── wallet.py            # 钱包
│   │   ├── disputes.py          # 争议处理
│   │   ├── core.py              # Core 集群 API
│   │   ├── internal.py          # 内部 API
│   │   └── ...
│   │
│   ├── services/                 # 业务服务
│   │   ├── matching.py          # 撮合引擎 (核心)
│   │   ├── node_status_store.py  # 节点状态存储
│   │   ├── escrow.py            # Escrow 服务
│   │   ├── verification.py      # 结果验证
│   │   ├── settlement.py        # 结算服务
│   │   ├── stake.py            # Stake 管理
│   │   ├── retry.py            # 重试机制
│   │   ├── pre_lock.py         # Pre-Lock 机制
│   │   ├── scoring.py           # 评分服务
│   │   ├── hard_filter.py      # 硬过滤
│   │   ├── cluster_builder.py  # Cluster 构建
│   │   └── queue/              # Job Queue
│   │       ├── job_queue.py     # 队列接口
│   │       ├── in_memory_queue.py  # 内存队列
│   │       └── redis_queue.py  # Redis 队列
│   │
│   ├── models/                   # 数据模型
│   │   ├── job.py              # Job 模型
│   │   ├── node.py             # Node 模型
│   │   ├── cluster.py          # Cluster 模型
│   │   ├── match.py            # Match 模型
│   │   ├── escrow.py           # Escrow 模型
│   │   ├── user.py             # 用户模型
│   │   ├── db_models.py        # 数据库模型
│   │   └── ...
│   │
│   ├── core/                    # Core 系统
│   │   ├── cluster/            # Core 集群
│   │   └── p2p/                # P2P 网络
│   │
│   ├── agents/                  # Agent
│   │   └── node_agent.py       # Node Agent
│   │
│   ├── repositories.py          # 数据访问层
│   ├── database.py             # 数据库配置
│   └── main.py                 # FastAPI 入口
│
├── node-agent/                   # Node Agent 源码
│   └── src/
│       ├── node_agent.py        # Agent 主程序
│       ├── runtime_adapter.py   # Runtime 适配器
│       ├── network.py           # 网络适配器
│       └── system_info.py       # 系统信息
│
├── tests/                        # 测试
│   ├── unit/                    # 单元测试
│   ├── test_*.py               # E2E 测试
│   └── conftest.py             # 测试配置
│
├── config.py                    # 配置文件
├── requirements.txt             # 依赖
└── run_node_agent.py           # Node Agent 启动脚本
```

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           DCM 架构                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐           │
│   │    Buyer     │────▶│     API      │◀────│    Node      │           │
│   │   (User)     │     │   Gateway    │     │  (Provider)  │           │
│   └──────────────┘     └──────┬───────┘     └──────────────┘           │
│                                │                                         │
│                    ┌────────────┼────────────┐                          │
│                    │            │            │                          │
│                    ▼            ▼            ▼                          │
│              ┌──────────┐ ┌──────────┐ ┌──────────┐                       │
│              │ Matching │ │  Escrow  │ │ Settlement│                       │
│              │ Service  │ │ Service  │ │ Service   │                       │
│              └────┬─────┘ └────┬────┘ └──────────┘                       │
│                   │            │                                       │
│                   ▼            ▼                                       │
│         ┌────────────────┐   ┌──────────┐                                │
│         │ NodeStatusStore │   │   DB    │                                │
│         │   (实时状态)    │   │ (持久化) │                                │
│         └────────────────┘   └──────────┘                                │
│                                                                         │
│                    ┌────────────▼────────────┐                          │
│                    │      Polygon Amoy        │                          │
│                    │   (Smart Contracts)      │                          │
│                    └─────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 核心流程

### 1. Job 提交流程

```
Buyer                    API                    Matching
  │                       │                       │
  │ POST /jobs            │                       │
  │──────────────────────▶│                       │
  │                       │                       │
  │                       │ 1. Create Job         │
  │                       │─────────────────────▶│
  │                       │                       │
  │                       │                       │ 2. trigger_match()
  │                       │                       │    └── _match()
  │                       │                       │
  │                       │                       │ 3. list_online_nodes()
  │                       │                       │    from NodeStatusStore
  │                       │                       │
  │                       │ 4. Create Match        │
  │                       │◀──────────────────────│
  │                       │                       │
  │                       │ 5. Save Escrow         │
  │                       │───────────────────────▶│
  │                       │                       │
  │  Response: job_id     │                       │
  │◀──────────────────────│                       │
```

### 2. Node 拉取流程 (Poll 模式)

```
Node Agent              API                    Matching
    │                    │                       │
    │ POST /poll         │                       │
    │───────────────────▶│                       │
    │                    │                       │
    │                    │ 1. poll_node()        │
    │                    │──────────────────────▶│
    │                    │                       │
    │                    │                       │ 2. get_node_info()
    │                    │                       │    from NodeStatusStore
    │                    │                       │
    │                    │                       │ 3. get_pending_jobs()
    │                    │                       │    from Queue
    │                    │                       │
    │                    │                       │ 4. _can_match() 过滤
    │                    │                       │
    │                    │                       │ 5. _create_match()
    │                    │ 6. Match / None       │
    │◀───────────────────│                       │
    │                    │                       │
    │ 7. Execute Job     │                       │
    │───────────────────▶│                       │
    │                    │                       │
```

### 3. Node 上报流程

```
Node Agent              API                    NodeStatusStore
    │                    │                       │
    │ POST /live_status  │                       │
    │───────────────────▶│                       │
    │                    │                       │
    │                    │ update_node_status()  │
    │                    │─────────────────────▶│
    │                    │                       │
    │ Response: OK       │                       │
    │◀───────────────────│                       │
    │                    │                       │
    │ POST /capacity_report (30-60s)            │
    │───────────────────▶│                       │
    │                    │                       │
    │                    │ update_node_status()  │
    │                    │ (with static config)  │
    │                    │─────────────────────▶│
```

---

## 📋 数据模型

### Job 模型

```python
class Job:
    job_id: str                    # Job ID
    user_id: str                   # 用户 ID
    model: Optional[str]           # 模型名称 (如 "qwen2.5:7b")
    messages: List[Message]        # 消息列表 (OpenAI 格式)
    input_tokens: int              # 输入 tokens
    output_tokens_limit: int       # 输出 tokens 上限
    max_latency: int              # 最大延迟 (ms)
    bid_price: float              # 出价 (USDC/1M tokens)
    status: JobStatus             # 状态
    cluster_id: Optional[str]     # 匹配的 Cluster
    node_id: Optional[str]        # 匹配的 Node
```

### Node 模型

```python
class Node:
    node_id: str                   # Node ID
    user_id: str                   # 所有者
    cluster_id: Optional[str]      # 所属 Cluster
    gpu_type: str                 # GPU 类型
    gpu_count: int                # GPU 数量
    runtime: Runtime               # 运行时
    pricing: Pricing              # 定价
    status: NodeStatus            # 状态
```

### NodeStatusInfo (实时状态)

```python
@dataclass
class NodeStatusInfo:
    # === 标识 ===
    node_id: str
    cluster_id: Optional[str]
    
    # === 实时状态 ===
    is_online: bool               # 是否在线 (10秒内有更新)
    last_update_ms: int           # 上次更新时间
    available_concurrency: int   # 可用并发
    available_queue_tokens: int   # 可用队列 tokens
    
    # === 静态配置 ===
    model_support: List[str]      # 支持的模型
    ask_price: float             # 要价
    avg_latency: int             # 平均延迟
    gpu_count: int               # GPU 数量
```

---

## 🌐 API 端点

### Jobs API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/jobs` | 提交 Job |
| GET | `/api/v1/jobs/{job_id}` | 获取 Job 状态 |
| GET | `/api/v1/jobs` | 列出 Jobs |
| POST | `/api/v1/jobs/{job_id}/cancel` | 取消 Job |
| POST | `/api/v1/jobs/{job_id}/result` | 提交结果 |

### Nodes API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/nodes` | 注册 Node |
| GET | `/api/v1/nodes/{node_id}` | 获取 Node 信息 |
| POST | `/api/v1/nodes/{node_id}/online` | 节点上线 |
| POST | `/api/v1/nodes/{node_id}/offline` | 节点下线 |
| POST | `/api/v1/nodes/{node_id}/poll` | 节点拉取 Job |
| POST | `/api/v1/nodes/{node_id}/live_status` | 上报实时状态 |
| POST | `/api/v1/nodes/{node_id}/capacity_report` | 上报容量信息 |
| POST | `/api/v1/nodes/{node_id}/stake/deposit` | 质押 |

### Users API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/users/register` | 注册用户 |
| POST | `/api/v1/users/login` | 用户登录 |
| GET | `/api/v1/users/{user_id}` | 获取用户信息 |

---

## 🔢 枚举类型

### JobStatus

```python
class JobStatus(str, Enum):
    CREATED = "created"       # 已创建
    PENDING = "pending"        # 等待撮合
    MATCHED = "matched"        # 已匹配
    PRE_LOCKED = "pre_locked"  # 预锁定
    RESERVED = "reserved"      # 已预约
    DISPATCHED = "dispatched"   # 已分发
    RUNNING = "running"        # 执行中
    COMPLETED = "completed"    # 完成
    FAILED = "failed"          # 失败
    CANCELLED = "cancelled"    # 取消
```

### NodeStatus

```python
class NodeStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    LOCKED = "locked"
```

### ClusterStatus

```python
class ClusterStatus(str, Enum):
    FREE = "free"
    PRE_LOCKED = "pre_locked"
    PARTIALLY_RESERVED = "partially_reserved"
    FULLY_RESERVED = "fully_reserved"
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    RELEASED = "released"
    OVERLOADED = "overloaded"
    FAILED = "failed"
```

---

## 🔧 配置说明

### config.py

```python
# 数据库
database_url: str = "sqlite:///./dcm.db"

# API
api_host: str = "0.0.0.0"
api_port: int = 8000

# 模型限制 (MVP)
mvp_model: str = "qwen2.5:7b"
max_output_tokens: int = 256
max_latency_ms: int = 30000

# Escrow
escrow_buffer: float = 1.1

# 结算
platform_fee_rate: float = 0.05  # 5%

# 验证
layer2_sample_rate: float = 0.1  # 10% 抽样

# Node Status Store
node_status_store_backend: str = "memory"  # 或 "redis"
node_status_store_ttl_seconds: int = 30

# Stake 分级
stake_personal: float = 50.0      # < 4 GPU
stake_professional: float = 200.0 # 4-7 GPU
stake_datacenter: float = 1000.0  # >= 8 GPU
```

---

## 📊 关键数据结构

### NodeStatusStore vs Database

| 数据类型 | NodeStatusStore | Database |
|----------|-----------------|----------|
| 实时状态 | ✅ available_concurrency | ❌ |
| 实时状态 | ✅ available_queue_tokens | ❌ |
| 实时状态 | ✅ is_online | ❌ |
| 静态配置 | ✅ model_support | ✅ |
| 静态配置 | ✅ ask_price | ✅ |
| 静态配置 | ✅ avg_latency | ✅ |
| 持久化 | ❌ | ✅ Node 注册 |
| 持久化 | ❌ | ✅ Job 记录 |
| 持久化 | ❌ | ✅ Match 记录 |
| 持久化 | ❌ | ✅ Escrow |

### 数据流向

```
Node Agent                              DCM Server
    │                                      │
    │ live_status (2-5s)                   │
    │─────────────────────────────────────▶│
    │                               NodeStatusStore
    │                                      │
    │ capacity_report (30-60s)             │
    │─────────────────────────────────────▶│
    │                               NodeStatusStore (static)
    │                                      │
    │ poll (拉取 Job)                      │
    │─────────────────────────────────────▶│
    │                               Matching Service
    │                                      │
    │                               list_online_nodes()  ◀──┐
    │                               from NodeStatusStore     │
    │                                                    │
    │                                                    │
    │              ┌───────────────────────────────────┘
    │              ▼
    │       Matching / DB
    │              │
    │◀─────────────────────────────────────│
    │       Match or None
```

---

## 🎯 匹配算法

### 两阶段分层匹配

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         匹配流程                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  第一阶段: 获取候选节点                                                 │
│  ─────────────────────────────────────────────                         │
│  online_nodes = list_online_nodes(max_age_seconds=10)                  │
│                                                                         │
│  第二阶段: 过滤与排序                                                   │
│  ─────────────────────────────────────────────                         │
│                                                                         │
│  1. 容量检查                                                           │
│     available_queue_tokens >= job_tokens                               │
│                                                                         │
│  2. 模型匹配                                                           │
│     job.model in node.model_support 或 前缀匹配                        │
│                                                                         │
│  3. 价格检查                                                           │
│     job.bid_price * 1M >= node.ask_price                              │
│                                                                         │
│  4. 延迟检查                                                           │
│     node.avg_latency <= job.max_latency                               │
│                                                                         │
│  第三阶段: 选择最优                                                     │
│  ─────────────────────────────────────────────                         │
│  candidates.sort(key=(ask_price, avg_latency))                         │
│  best_node = candidates[0]                                             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📝 Cluster ID 格式

```
cluster_id: C_{region}{tier}_{model}{rel}_{hash}

示例:
  C_usw_P_Q_A_3f2e

分解:
  C       - 前缀
  usw     - 区域 (us-west)
  P       - 等级 (Personal)
  Q       - 模型家族 (Qwen)
  A       - 可靠性 (A 级)
  3f2e    - 哈希
```

---

## 🔐 Stake 分级

| 等级 | Stake 金额 | GPU 数量 | Tier Code |
|------|-----------|----------|-----------|
| Personal | 50 USDC | < 4 GPU | P |
| Professional | 200 USDC | 4-7 GPU | X |
| Enterprise | 1000 USDC | >= 8 GPU | E |

---

## 🚀 启动方式

### 启动 DCM Server

```bash
cd DCM
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 启动 Node Agent

```bash
cd DCM
python run_node_agent.py
```

---

## 📚 相关文档

- [README.md](./README.md) - 项目说明
- [README_CN.md](./README_CN.md) - 中文说明
- [DEVELOPMENT.md](./DEVELOPMENT.md) - 开发指南
- [TODO.md](./TODO.md) - 待办事项

---

## 🔗 快速链接

- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health
- 重启时读取此文档了解项目结构
