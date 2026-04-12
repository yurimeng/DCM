# DCM - Decentralized Compute Market

> 去中心化 AI 推理市场

## 项目概述

构建全球去中心化 AI 推理市场，使任何人都可以出售或购买算力。

**当前阶段**：MVP（验证期）

### MVP 验证目标

| 验证问题 | 成功标准 |
|---------|---------|
| **技术** | Job 完整跑完：提交→执行→结果返回→结算 |
| **市场** | 价格由市场形成，不是设定的 |
| **经济** | 节点有收益留存，买家比集中式 API 便宜 |

## 核心模块（F1-F8）

| 模块 | 名称 | 优先级 |
|------|------|-------|
| F1 | Job 提交与管理系统 | P0 |
| F2 | 节点注册与状态管理 | P0 |
| F3 | 撮合引擎 | P0 |
| F4 | 失败重试机制 | P0 |
| F5 | 验证服务 | P0 |
| F6 | 结算服务 | P0 |
| F7 | Stake 管理与争议处理 | P1 |
| F8 | 技术架构与数据流 | P0 |

## 技术栈

| 组件 | 技术 |
|------|------|
| API 层 | FastAPI (Python) |
| 数据库 | SQLite (MVP) / PostgreSQL (PRD 1.0) |
| 结算链 | Solana / Base (USDC) |
| 验证 | SHA256 + ROUGE-L |
| 节点通信 | WebSocket + HTTP |

## 目录结构

```
DCM/
├── src/
│   ├── api/          # API 路由
│   ├── core/         # 核心业务逻辑
│   ├── services/     # 服务层（F1-F7）
│   ├── models/       # 数据模型
│   ├── agents/       # Node Agent 客户端
│   └── utils/        # 工具函数
├── tests/
│   ├── unit/         # 单元测试
│   ├── integration/  # 集成测试
│   └── e2e/          # E2E 测试
├── infra/
│   ├── docker/       # Docker 配置
│   ├── k8s/          # Kubernetes 配置
│   └── scripts/      # 运维脚本
├── docs/             # 文档
└── .github/workflows/ # CI/CD
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python scripts/init_db.py

# 启动服务
uvicorn src.api.main:app --reload

# 运行测试
pytest tests/
```

## 相关文档

- **PRD**: `Decentralized Compute Market/PRD/PRD 0.2：MVP定义稿（修订版）`
- **Function**: `Decentralized Compute Market/Function/Function 模块索引`
- **Principle**: `Decentralized Compute Market/Principle`

## 约束

| 红线 | 内容 |
|------|------|
| DCM-01 | Stake 必须链上合约，不能进系统账户 |
| DCM-02 | 不能人工指定节点，Router 撮合不可干预 |
| DCM-03 | Layer 1 验证必须在线 |
| DCM-04 | 争议：冻结不扣除，Buyer 不获补偿 |

---

*文档位置：Obsidian Vault `Decentralized Compute Market/`*
