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

F2 节点注册 ── F7 Stake
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

### Sprint 2: 核心业务逻辑 🔴

| 任务 | 优先级 | 依赖 | 工作量 |
|------|--------|------|--------|
| F3 撮合引擎完善 | P0 | Sprint 1 | 6h |
| F5 验证服务完善 | P0 | F3 | 4h |
| F4 失败重试机制 | P0 | F3, F5 | 4h |
| F6 结算服务完善 | P0 | F5 | 4h |
| F7 Stake 服务完善 | P1 | F5 | 3h |

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

## 三、P0 上线前必须完成

### PRD 开放问题

| 问题 | 行动项 | 负责人 | 状态 |
|------|--------|--------|------|
| Q1: Layer 2 相似度阈值 | MVP 前用 100+ Job 跑基准 | 待定 | 🔴 |
| Q2: Stake 门槛确认 | 5-10 个节点访谈 | 待定 | 🔴 |
| Q3: Node Agent 规范 | 完成 F2-NodeAgent 规范 | 待定 | 🔴 |

### 技术闭环标准

| 指标 | 通过标准 | 当前状态 |
|------|---------|---------|
| 全流程延迟 | < 10s | 🔴 |
| 结算自动化 | 100% | 🟡 |
| Escrow 完整性 | 无丢失 | 🟡 |
| 验证机制 | Layer1 + Layer2 | 🟡 |

---

## 四、代码目录结构

```
~/Code/Platform/DCM/
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置
│   ├── database.py          # 数据库配置
│   ├── repositories.py      # Repository 层
│   ├── api/                 # API 路由
│   │   ├── __init__.py
│   │   ├── jobs.py          # F1 Job API
│   │   └── nodes.py         # F2 Node API
│   ├── core/                # 核心逻辑
│   ├── services/            # 服务层
│   │   ├── escrow.py        # F6 结算
│   │   ├── matching.py      # F3 撮合
│   │   ├── verification.py  # F5 验证
│   │   ├── retry.py         # F4 重试
│   │   └── stake.py         # F7 Stake
│   ├── models/              # 数据模型
│   │   ├── job.py
│   │   ├── node.py
│   │   ├── match.py
│   │   ├── escrow.py
│   │   └── db_models.py     # SQLAlchemy ORM
│   ├── agents/              # Node Agent 客户端
│   └── utils/               # 工具函数
├── tests/
│   ├── conftest.py          # Pytest fixtures
│   ├── unit/
│   │   ├── test_models.py
│   │   └── test_api.py
│   ├── integration/
│   └── e2e/
├── scripts/
│   └── init_db.py           # 数据库初始化
├── infra/
│   ├── docker/
│   ├── k8s/
│   └── scripts/
├── docs/
├── requirements.txt
├── pytest.ini
├── config.py
├── README.md
└── DEVELOPMENT.md
```

---

## 五、技术栈

| 组件 | 当前选择 | 说明 |
|------|---------|------|
| API | FastAPI | REST + 可选 WebSocket |
| 数据库 | SQLite | MVP; PostgreSQL (1.0) |
| ORM | SQLAlchemy | 数据访问 |
| 链 | Solana/Base | USDC 结算 |
| 验证 | SHA256 + ROUGE-L | Layer 1 + Layer 2 |
| 测试 | pytest | 单元 + 集成测试 |

---

## 六、测试覆盖

| 指标 | 值 |
|------|------|
| 测试总数 | 29 |
| 通过率 | 100% |
| 代码覆盖率 | 73% |

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

## 八、下一步行动

1. **Sprint 2**: 完善 F3-F7 核心业务逻辑
2. **Sprint 3**: Node Agent SDK 开发
3. **Sprint 4**: 链上 Escrow/Stake 合约
