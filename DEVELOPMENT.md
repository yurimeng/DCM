# DCM MVP 开发计划

> 基于 PRD 0.2 & Function 定义

---

## 一、模块依赖关系

```
F1 Job提交 ──┬── F3 撮合 ──┬── F5 验证 ──┬── F6 结算
            │             │             │
            │             │             └── F4 重试
            │             │
            │             └── F2 节点状态
            │
            └── F6 Escrow

F2 节点注册 ── F7 Stake/争议
```

---

## 二、Sprint 规划

### Sprint 0: 基础设施 ✅

| 任务 | 状态 | 说明 |
|------|------|------|
| 项目结构 | ✅ | src/, tests/, infra/, docs/ |
| 配置管理 | ✅ | config.py, .env.example |
| 数据模型 | ✅ | Job, Node, Match, Escrow |
| 核心服务 | ✅ | Escrow, Matching, Verification, Retry, Stake |
| API 路由 | ✅ | /api/v1/jobs, /api/v1/nodes |
| 单元测试 | ✅ | 基本测试覆盖 |

### Sprint 1: API 完善 + 数据库 ✅

| 任务 | 状态 | 说明 |
|------|------|------|
| 数据库集成 | ✅ | SQLAlchemy + SQLite |
| F1 Job API 完善 | ✅ | CRUD + Escrow |
| F2 Node API 完善 | ✅ | 注册/上线/拉取 |
| Repository 层 | ✅ | 数据访问抽象 |
| 测试覆盖 | ✅ | 29 tests, 73% coverage |

### Sprint 2: 核心业务逻辑 ✅

| 任务 | 状态 | 说明 |
|------|------|------|
| Internal API | ✅ | /internal/v1/* 端点 |
| F3 撮合完善 | ✅ | 数据库持久化 |
| F4 重试机制 | ✅ | 2次重试，排他节点 |
| F5 验证服务 | ✅ | Layer1 + 10% Layer2 |
| F6 结算服务 | ✅ | 95%/5% 分配 |
| F7 争议/申诉 | ✅ | 冻结/申诉 API |
| 测试覆盖 | ✅ | 48 tests, 67% coverage |

### Sprint 3: 节点客户端 🔴

| 任务 | 优先级 | 依赖 | 工作量 |
|------|--------|------|--------|
| Node Agent 规范 | P0 | Sprint 2 | 2h |
| Node Agent SDK | P0 | 规范 | 8h |
| WebSocket 通信 | P1 | SDK | 4h |
| 心跳机制 | P0 | SDK | 2h |

### Sprint 4: 链上集成 🔴

| 任务 | 优先级 | 依赖 | 工作量 |
|------|--------|------|--------|
| Escrow 合约接口 | P0 | Sprint 2 | 6h |
| Stake 合约接口 | P0 | Sprint 3 | 4h |
| USDC 转账集成 | P0 | 合约 | 4h |
| 链上事件监听 | P1 | 合约 | 3h |

### Sprint 5: 测试 + 部署 🔴

| 任务 | 优先级 | 依赖 | 工作量 |
|------|--------|------|--------|
| 集成测试 | P0 | Sprint 1-4 | 8h |
| E2E 测试 | P0 | Sprint 4 | 6h |
| Docker 配置 | P0 | Sprint 0 | 2h |
| CI/CD 配置 | P1 | Docker | 4h |
| 部署文档 | P1 | CI/CD | 2h |

---

## 三、API 端点总览

### Jobs API (`/api/v1/jobs`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/jobs` | POST | 创建 Job |
| `/jobs/{job_id}` | GET | 获取详情 |
| `/jobs/{job_id}/escrow` | GET | Escrow 状态 |
| `/jobs` | GET | 列表 |
| `/jobs/stats/summary` | GET | 统计 |

### Nodes API (`/api/v1/nodes`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/nodes` | POST | 注册节点 |
| `/nodes/{node_id}` | GET | 详情 |
| `/nodes/{node_id}/online` | POST | 上线 |
| `/nodes/{node_id}/offline` | POST | 下线 |
| `/nodes/{node_id}/poll` | POST | 拉取 Job |
| `/nodes/{node_id}/jobs/{job_id}/result` | POST | 提交结果 |
| `/nodes/{node_id}/stake/deposit` | POST | 存款确认 |
| `/nodes/{node_id}/status` | GET | 状态 |

### Internal API (`/internal/v1`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/match/trigger` | POST | 触发撮合 |
| `/match/poll` | POST | 节点拉取 |
| `/verify` | POST | 验证结果 |
| `/verify/layer2` | POST | Layer2 结果 |
| `/settlement/execute` | POST | 执行结算 |
| `/retry/handle` | POST | 处理重试 |
| `/stake/freeze` | POST | 冻结 Stake |
| `/disputes/{id}` | GET | 争议详情 |
| `/stats/failures` | GET | 失败统计 |
| `/stats/verification` | GET | 验证统计 |

### Disputes API (`/api/v1/disputes`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/disputes/{id}` | GET | 争议详情 |
| `/disputes/node/{node_id}` | GET | 节点争议 |
| `/disputes` | GET | 列表 |
| `/disputes/{id}/appeals` | POST | 提交申诉 |
| `/disputes/{id}/appeals/{id}` | GET | 申诉详情 |
| `/disputes/appeals` | GET | 申诉列表 |
| `/disputes/stats/summary` | GET | 统计 |

---

## 四、核心公式

### Escrow 计算
```
escrow_amount = bid_price × (input_tokens + output_tokens_limit) / 1M × 1.1
```

### 结算分配
```
cost = locked_price × actual_tokens / 1M
node_earn = cost × 0.95
platform_fee = cost × 0.05
refund = locked_amount - cost
```

### 撮合条件
```
job.bid_price >= node.ask_price
node.avg_latency <= job.max_latency
node.status == "online"
node.model_support contains job.model
```

### 延迟处罚
```
mild_penalty: max_latency < latency <= max_latency × 1.5 → cost × 0.7
failure: latency > max_latency × 1.5 → refund 100%
```

---

## 五、技术栈

| 组件 | 技术 |
|------|------|
| API | FastAPI |
| 数据库 | SQLite (MVP) → PostgreSQL (1.0) |
| ORM | SQLAlchemy |
| 链 | Solana/Base (USDC) |
| 验证 | SHA256 + ROUGE-L (简化) |
| 测试 | pytest |

---

## 六、测试结果

| Sprint | 测试数 | 通过 | 覆盖率 |
|--------|--------|------|--------|
| Sprint 0 | 14 | 14 | 47% |
| Sprint 1 | 15 | 15 | 65% |
| Sprint 2 | 19 | 19 | 67% |
| **总计** | **48** | **48** | **67%** |

---

## 七、启动命令

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python scripts/init_db.py

# 启动服务
uvicorn src.main:app --reload

# 运行测试
pytest tests/ -v

# 运行测试（带覆盖率）
pytest tests/ --cov=src --cov-report=html
```

---

## 八、下一步

1. **Sprint 3**: Node Agent SDK 开发
2. **Sprint 4**: 链上 Escrow/Stake 合约
3. **Sprint 5**: 集成测试 + 部署
