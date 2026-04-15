# DCM - Decentralized Compute Market

> 去中心化 AI 推理市场 | 任何人可以买卖算力
>
> **版本**: v3.2 | **状态**: MVP | **E2E 测试**: ✅ 10/10 通过

---

## 目录

- [快速开始](#快速开始)
- [系统架构](#系统架构)
- [模块描述](#模块描述)
- [核心流程](#核心流程)
- [接口列表](#接口列表)
- [数据模型](#数据模型)
- [配置说明](#配置说明)

---

## 快速开始

### 环境要求

- Python 3.10+
- Ollama (用于推理)
- SQLite (默认)

### 安装运行

```bash
# 1. 克隆项目
git clone https://github.com/yurimeng/DCM.git
cd DCM

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 Ollama
ollama serve &
ollama pull qwen2.5:7b

# 4. 启动 DCM
rm -f dcm.db  # 可选：重置数据库
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 5. 访问 API 文档
# http://localhost:8000/docs
```

### Docker 部署

```bash
docker run -p 8000:8000 ghcr.io/yurimeng/dcm:v3.2
```

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           DCM 系统架构                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐  │
│   │    Buyer     │         │     API      │         │    Node      │  │
│   │   (用户)     │────────▶│   Gateway    │◀────────│  (算力提供者) │  │
│   └──────────────┘         └──────┬───────┘         └──────────────┘  │
│                                   │                                        │
│                    ┌──────────────┼──────────────┐                        │
│                    │              │              │                        │
│                    ▼              ▼              ▼                        │
│              ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│              │ Matching  │  │  Escrow   │  │ Settlement│                   │
│              │ Service   │  │  Service  │  │  Service  │                   │
│              │  撮合引擎  │  │  资金托管  │  │   结算    │                   │
│              └─────┬─────┘  └─────┬─────┘  └──────────┘                   │
│                    │              │                                       │
│                    ▼              ▼                                       │
│              ┌────────────────┐  ┌──────────┐                            │
│              │ NodeStatusStore│  │ Database  │                            │
│              │  (实时状态)    │  │ (SQLite)  │                            │
│              └────────────────┘  └──────────┘                            │
│                                                                         │
│                    ┌────────────▼────────────┐                         │
│                    │      Job Queue           │                         │
│                    │    (优先级队列)           │                         │
│                    └─────────────────────────┘                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 模块描述

### 1. API 层 (`src/api/`)

| 模块 | 文件 | 职责 |
|------|------|------|
| **Jobs API** | `jobs.py` | Job 提交、查询、取消 |
| **Nodes API** | `nodes.py` | Node 注册、状态管理 |
| **Users API** | `users.py` | 用户注册、登录 |
| **Internal API** | `internal.py` | 内部管理接口 |

### 2. 服务层 (`src/services/`)

| 模块 | 文件 | 职责 |
|------|------|------|
| **Matching Service** | `matching.py` | 撮合引擎，匹配 Job 与 Node |
| **NodeStatusStore** | `node_status_store.py` | 实时节点状态存储 |
| **Escrow Service** | `escrow.py` | 资金托管与锁定 |
| **Verification** | `verification.py` | 结果验证服务 |
| **Job Queue** | `queue/` | 优先级队列管理 |
| **PreLock** | `pre_lock.py` | 预锁定机制 |

### 3. 数据模型层 (`src/models/`)

| 模块 | 文件 | 职责 |
|------|------|------|
| **Job** | `job.py` | Job 数据模型 |
| **Node** | `node.py` | Node 数据模型 |
| **Match** | `match.py` | 匹配记录模型 |
| **Escrow** | `escrow.py` | Escrow 模型 |
| **Cluster** | `cluster.py` | Cluster 数据模型 |

### 4. 数据访问层 (`src/`)

| 模块 | 文件 | 职责 |
|------|------|------|
| **Database** | `database.py` | SQLAlchemy 数据库配置 |
| **Repositories** | `repositories.py` | 数据访问抽象 |

### 5. 核心模块 (`src/core/`)

| 模块 | 文件 | 职责 |
|------|------|------|
| **Cluster** | `cluster/` | 集群管理 |
| **P2P** | `p2p/` | P2P 网络 |
| **Wallet** | `wallet.py` | 钱包服务 |

---

## 核心流程

### 流程 1: Job 提交与撮合

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Job 提交与撮合流程                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Buyer                API                    Matching Service            │
│    │                  │                            │                     │
│    │ POST /jobs      │                            │                     │
│    │────────────────▶│                            │                     │
│    │                  │                            │                     │
│    │                  │ 1. 创建 Job                 │                     │
│    │                  │──────────────────────────▶│                     │
│    │                  │                            │                     │
│    │                  │ 2. 创建 Escrow             │                     │
│    │                  │──────────────────────────▶│                     │
│    │                  │                            │                     │
│    │                  │ 3. 触发 trigger_match()    │                     │
│    │                  │──────────────────────────▶│                     │
│    │                  │                            │                     │
│    │                  │ 4. 查询在线节点             │                     │
│    │                  │    list_online_nodes()     │                     │
│    │                  │                            │                     │
│    │                  │ 5. 过滤候选节点             │                     │
│    │                  │    - 模型匹配              │                     │
│    │                  │    - 价格满足              │                     │
│    │                  │    - 延迟满足              │                     │
│    │                  │    - 容量满足              │                     │
│    │                  │                            │                     │
│    │                  │ 6. 选择最优节点             │                     │
│    │                  │    (最低价优先)            │                     │
│    │                  │                            │                     │
│    │                  │ 7. 创建 Match              │                     │
│    │                  │◀──────────────────────────│                     │
│    │                  │                            │                     │
│    │                  │ 8. 返回 job_id              │                     │
│    │◀─────────────────│                            │                     │
│    │  {job_id, status}│                            │                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 流程 2: Node 拉取与执行

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Node 拉取与执行流程                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Node Agent           API                    Matching Service           │
│       │               │                            │                    │
│       │ POST /poll    │                            │                    │
│       │──────────────▶│                            │                    │
│       │               │                            │                    │
│       │               │ 1. poll_node()             │                    │
│       │               │───────────────────────────▶│                    │
│       │               │                            │                    │
│       │               │ 2. 检查节点状态             │                    │
│       │               │    is_online?               │                    │
│       │               │                            │                    │
│       │               │ 3. 获取待匹配 Jobs          │                    │
│       │               │    queue.get_pending_jobs()  │                    │
│       │               │                            │                    │
│       │               │ 4. 匹配检查                 │                    │
│       │               │    _can_match()            │                    │
│       │               │                            │                    │
│       │               │ 5. 返回 Match              │                    │
│       │               │◀──────────────────────────│                    │
│       │  {job}        │                            │                    │
│       │◀──────────────│                            │                    │
│       │               │                            │                    │
│       │───────────────│                            │                    │
│       │ 执行推理请求   │                            │                    │
│       │───────────────│                            │                    │
│       │               │                            │                    │
│       │ POST /result  │                            │                    │
│       │──────────────▶│                            │                    │
│       │               │                            │                    │
│       │  {received}   │                            │                    │
│       │◀──────────────│                            │                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 流程 3: 状态上报

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           状态上报流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Node Agent                     NodeStatusStore                         │
│       │                                │                                 │
│       │  POST /live_status (2-5s)     │                                 │
│       │────────────────────────────────▶│                                 │
│       │  {timestamp, status, load}    │                                 │
│       │                                │                                 │
│       │                                │ 更新实时状态                      │
│       │                                │ is_online = True               │
│       │  {received}                    │                                 │
│       │◀────────────────────────────────│                                 │
│       │                                │                                 │
│       │  POST /capacity_report (30-60s)│                                 │
│       │────────────────────────────────▶│                                 │
│       │  {runtime, models, capacity}  │                                 │
│       │                                │                                 │
│       │                                │ 更新静态配置                      │
│       │                                │ - model_support                  │
│       │                                │ - ask_price                     │
│       │  {received, cluster_id}        │                                 │
│       │◀────────────────────────────────│                                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 流程 4: 结算流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           结算流程                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Job 完成                   Escrow Service          Settlement          │
│       │                            │                      │             │
│       │ 1. 提交结果                 │                      │             │
│       │────────────────────────────▶│                      │             │
│       │                            │                      │             │
│       │                            │ 2. 锁定状态           │             │
│       │                            │    LOCKED            │             │
│       │                            │                      │             │
│       │                            │ 3. 延迟自动结算       │             │
│       │                            │    (5分钟)           │             │
│       │                            │─────────────────────▶│             │
│       │                            │                      │             │
│       │                            │                      │ 4. 计算费用  │
│       │                            │                      │             │
│       │                            │ 5. 分配资金           │             │
│       │                            │    Node: 95%         │             │
│       │                            │    Platform: 5%      │             │
│       │                            │    余额退款          │             │
│       │                            │                      │             │
│       │                            │ 6. 更新状态           │             │
│       │                            │    SETTLED          │             │
│       │                            │                      │             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 接口列表

### Jobs API (`/api/v1/jobs`)

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| `POST` | `/jobs` | 创建 Job (DCM 格式) | `JobCreate` |
| `POST` | `/jobs/openai` | 创建 Job (OpenAI 兼容) | `JobCreateOpenAI` |
| `GET` | `/jobs/{job_id}` | 获取 Job 详情 | - |
| `GET` | `/jobs` | 列出 Jobs | `?status=&limit=&offset=` |
| `POST` | `/jobs/{job_id}/cancel` | 取消 Job | - |
| `POST` | `/jobs/{job_id}/prelock` | 预锁定 Job | - |
| `POST` | `/jobs/{job_id}/prelock/ack` | 确认预锁定 | `PreLockACKRequest` |
| `GET` | `/jobs/{job_id}/escrow` | 获取 Escrow 状态 | - |

#### 请求/响应示例

**创建 Job (OpenAI 格式)**:
```bash
curl -X POST http://localhost:8000/api/v1/jobs/openai \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:7b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

**响应**:
```json
{
  "job_id": "job_abc123",
  "escrow_amount": 0.00028,
  "status": "matched",
  "created_at": "2024-01-01T00:00:00",
  "matched_at": "2024-01-01T00:00:01"
}
```

---

### Nodes API (`/api/v1/nodes`)

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| `POST` | `/nodes` | 注册 Node | `NodeCreate` |
| `GET` | `/nodes/{node_id}` | 获取 Node 信息 | - |
| `POST` | `/nodes/{node_id}/online` | 节点上线 | - |
| `POST` | `/nodes/{node_id}/offline` | 节点下线 | - |
| `POST` | `/nodes/{node_id}/poll` | 拉取 Job | - |
| `POST` | `/nodes/{node_id}/live_status` | 上报实时状态 | `LiveStatusReport` |
| `POST` | `/nodes/{node_id}/capacity_report` | 上报容量信息 | `CapacityReport` |
| `POST` | `/nodes/{node_id}/result` | 提交执行结果 | `NodeResultSubmit` |
| `POST` | `/nodes/{node_id}/stake/deposit` | 质押存款 | `tx_hash` |
| `GET` | `/nodes/{node_id}/status` | 获取节点状态 | - |

#### 请求/响应示例

**注册 Node**:
```bash
curl -X POST http://localhost:8000/api/v1/nodes \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "runtime": {
      "type": "ollama",
      "loaded_models": ["qwen2.5:7b"]
    },
    "hardware": {
      "gpu_type": "RTX 4090",
      "gpu_count": 1
    },
    "pricing": {
      "ask_price": 0.000001
    }
  }'
```

**响应**:
```json
{
  "node_id": "node_xyz789",
  "status": "online",
  "stake_required": 50.0,
  "next_step": "Deposit 50.0 USDC to activate"
}
```

---

### Users API (`/api/v1/users`)

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/users/register` | 注册用户 |
| `POST` | `/users/login` | 用户登录 |
| `GET` | `/users/{user_id}` | 获取用户信息 |
| `GET` | `/users/{user_id}/wallet` | 获取钱包信息 |

---

### 内部接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/internal/stats` | 系统统计 |
| `GET` | `/internal/jobs/pending` | 待撮合 Jobs |
| `GET` | `/internal/nodes/online` | 在线 Nodes |

---

## 数据模型

### Job 状态流转

```
┌─────────┐    ┌─────────┐    ┌───────────┐    ┌──────────┐
│ CREATED │───▶│ PENDING │───▶│  MATCHED  │───▶│ RESERVED │
└─────────┘    └─────────┘    └───────────┘    └──────────┘
                                     │                  │
                                     ▼                  ▼
                              ┌───────────┐       ┌──────────┐
                              │ PRE_LOCKED│       │ DISPATCHED│
                              └───────────┘       └──────────┘
                                     │                  │
                                     ▼                  ▼
                              ┌───────────┐       ┌──────────┐
                              │ CANCELLED │       │  RUNNING  │
                              └───────────┘       └──────────┘
                                                             │
                              ┌───────────┐                   │
                              │  FAILED   │◀──────────────────┘
                              └───────────┘                   │
                                                             ▼
                                                      ┌──────────┐
                                                      │ COMPLETED│
                                                      └──────────┘
```

### Node 状态

| 状态 | 说明 |
|------|------|
| `OFFLINE` | 离线 |
| `ONLINE` | 在线，可接 Job |
| `BUSY` | 忙碌，执行中 |
| `LOCKED` | 被锁定 |

### Escrow 状态

| 状态 | 说明 |
|------|------|
| `LOCKED` | 已锁定，等待结算 |
| `COMPLETED` | Job 完成，等待自动结算 |
| `SETTLED` | 已结算 |
| `CANCELLED` | 已取消（退款） |
| `REFUNDED` | 已退款 |

---

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DCM_DATABASE_URL` | `sqlite:///./dcm.db` | 数据库连接 |
| `DCM_DEBUG` | `true` | 调试模式 |
| `DCM_API_PORT` | `8000` | API 端口 |
| `DCM_MVP_MODEL` | `qwen2.5:7b` | MVP 模型 |

### MVP 配置

```python
# config.py
MVP_MODE = True
MVP_MODEL = "qwen2.5:7b"
MAX_OUTPUT_TOKENS = 256
MAX_LATENCY_MS = 30000

# 价格 (USDC/token)
DEFAULT_BID_PRICE = 0.000001  # 1 USDC/1M tokens
DEFAULT_ASK_PRICE = 0.000001

# 结算
PLATFORM_FEE_RATE = 0.05  # 5%
NODE_EARN_RATE = 0.95  # 95%
```

---

## 监控与调试

### 健康检查

```bash
curl http://localhost:8000/health
```

**响应**:
```json
{
  "status": "healthy",
  "version": "3.2"
}
```

### 系统统计

```bash
curl http://localhost:8000/stats
```

**响应**:
```json
{
  "system": {
    "version": "3.2",
    "mvp_mode": true
  },
  "matching": {
    "pending_jobs": 5,
    "online_nodes": 3
  },
  "queue_stats": {
    "type": "InMemoryJobQueue",
    "size": 5
  }
}
```

### API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

## 测试

### 运行测试

```bash
# 全部测试
pytest tests/

# E2E 测试
python scripts/test_e2e_10_jobs.py

# 单元测试
pytest tests/unit/
```

### E2E 测试结果 (v3.2)

```
============================================================
E2E Test - 10 Jobs Complete Flow
============================================================
Passed: 10/10 ✅
============================================================
```

---

## 版本历史

| 版本 | 日期 | 状态 | 说明 |
|------|------|------|------|
| 3.0 | 2024-04-12 | ✅ | 基础 Match Engine |
| 3.1 | 2024-04-13 | ✅ | Pre-Lock, Slot 抽象 |
| **3.2** | 2024-04-15 | **✅ MVP** | OpenAI API, NodeStatusStore |

---

## 相关文档

- [项目概览](./PROJECT_OVERVIEW.md)
- [代码审查报告](./docs/CODE_REVIEW.md)
- [Match Engine 架构](./docs/DCM-v3.2-Architecture.md)
- [函数索引](./Function/Function 模块索引.md)
