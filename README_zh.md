# DCM - 去中心化算力市场

> Decentralized Compute Market，一个任何人都可以买卖算力的去中心化 AI 推理市场。

## 项目概述

DCM 构建一个全球化的去中心化 AI 推理市场，实现算力的无许可交易。

**当前阶段**：MVP（最小可行产品验证期）

### MVP 验证目标

| 验证领域 | 成功标准 |
|---------|---------|
| **技术** | Job 完整跑通：提交 → 执行 → 结果返回 → 结算 |
| **市场** | 价格由市场机制形成，而非预设 |
| **经济** | 节点运营商有收益，买家比中心化 API 更便宜 |

## 核心模块 (F1-F15)

### 第一阶段：核心基础设施 (F1-F8)

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

### 第二阶段：网络层 (F9-F15)

| 模块 | 名称 | 优先级 |
|------|------|-------|
| F9 | Core Cluster 核心集群 | P0 |
| F10 | Scaler 自动扩缩容 | P0 |
| F11 | Worker Pool 工作池 | P0 |
| F13 | P2P Network 点对点网络 | P0 |
| F14 | QUIC Transport 传输层 | P0 |
| F15 | Relay Service 中继服务 | P0 |

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        API 层 (FastAPI)                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │   Jobs   │  │  Nodes   │  │  Wallet  │  │  Disputes │  │
│  │  任务    │  │  节点    │  │  钱包   │  │  争议   │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │            │            │            │             │
│       └────────────┴────────────┴────────────┘             │
│                          │                                  │
│       ┌───────────────────┴───────────────────┐             │
│       │          Core Cluster (F9)             │             │
│       │  ┌──────────┐  ┌──────────┐          │             │
│       │  │ Scaler   │──│  Worker  │          │             │
│       │  │  (F10)   │  │  Pool    │          │             │
│       │  │  自动扩缩 │  │  (F11)   │          │             │
│       │  └──────────┘  │  工作池  │          │             │
│       │                └────┬─────┘          │             │
│       │                     │                │             │
│       └─────────────────────┼────────────────┘             │
│                             │                              │
│       ┌─────────────────────┼─────────────────────┐        │
│       │        Network Layer (F13-F15)           │        │
│       │  ┌────────┐  ┌────────┐  ┌────────┐    │        │
│       │  │  P2P   │──│  QUIC  │──│ Relay  │    │        │
│       │  │ (F13)  │  │ (F14)  │  │ (F15)  │    │        │
│       │  │ 点对点 │  │ 传输层 │  │ 中继   │    │        │
│       │  └────────┘  └────────┘  └────────┘    │        │
│       └─────────────────────────────────────────┘        │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                    Service Layer (F1-F7)                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │  Matching   │  │ Verification│ │ Settlement │            │
│  │   撮合引擎  │  │   验证服务  │ │   结算服务  │            │
│  └────────────┘  └────────────┘  └────────────┘            │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                    Blockchain (Solana/Base)                   │
│  ┌────────────┐  ┌────────────┐                            │
│  │  Escrow    │  │   Stake    │                            │
│  │  托管合约   │  │  质押合约   │                            │
│  └────────────┘  └────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

## 网络冗余机制

```
┌─────────────────────────────────────────────────────────────┐
│                   网络故障恢复机制                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Worker 网络中断                                          │
│     ↓                                                        │
│  2. p2p_connected = False                                   │
│     ↓                                                        │
│  3. 心跳超时检测 (60秒)                                       │
│     ↓                                                        │
│  4. 自动重连 (10秒间隔)                                       │
│     ├── 尝试直连                                             │
│     └── 失败 → 回退到 Relay                                  │
│     ↓                                                        │
│  5. 重连成功 → 恢复服务                                      │
│     或                                                       │
│  5. 重连失败 → retry_count++                                 │
│     ↓                                                        │
│  6. retry_count >= 5 → 标记为不可用                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈

| 组件 | 技术 |
|------|------|
| API 层 | FastAPI (Python 3.11+) |
| 数据库 | SQLite (MVP) / PostgreSQL (生产环境) |
| 结算链 | Solana / Base (USDC) |
| 验证 | SHA256 + ROUGE-L |
| 节点通信 | WebSocket + HTTP + QUIC |
| P2P 网络 | 自定义 asyncio 实现 |

## 项目结构

```
DCM/
├── src/
│   ├── api/              # API 路由
│   │   ├── core.py       # 核心集群端点 (F9)
│   │   ├── scaler.py     # 扩缩容端点 (F10)
│   │   ├── worker_pool.py# 工作池端点 (F11)
│   │   ├── p2p.py        # P2P 端点 (F13)
│   │   ├── quic.py       # QUIC 端点 (F14)
│   │   ├── relay.py      # 中继端点 (F15)
│   │   ├── jobs.py       # 任务端点 (F1)
│   │   ├── nodes.py      # 节点端点 (F2)
│   │   ├── wallet.py     # 钱包端点
│   │   └── disputes.py   # 争议端点 (F7)
│   │
│   ├── core/             # 核心业务逻辑
│   │   ├── cluster/      # 核心集群服务
│   │   │   ├── cluster_service.py   # 集群管理
│   │   │   ├── scaler_service.py    # 自动扩缩容
│   │   │   └── worker_pool.py       # 工作池
│   │   ├── p2p/          # P2P 网络 (F13)
│   │   │   ├── p2p_service.py       # P2P 实现
│   │   │   └── models.py            # P2P 模型
│   │   ├── quic/         # QUIC 传输 (F14)
│   │   └── relay/        # 中继服务 (F15)
│   │
│   ├── services/         # 服务层 (F1-F7)
│   │   ├── matching.py   # 撮合引擎
│   │   ├── verification.py# 验证服务
│   │   ├── escrow.py     # 托管服务
│   │   ├── stake.py      # 质押管理
│   │   ├── retry.py      # 重试机制
│   │   └── chain_sync.py # 链上同步
│   │
│   ├── models/           # 数据模型
│   ├── agents/           # 节点代理客户端
│   └── utils/            # 工具函数
│
├── tests/
│   ├── unit/             # 单元测试
│   ├── integration/      # 集成测试
│   └── e2e/              # 端到端测试
│
├── contracts/            # 区块链合约
│   ├── Escrow.sol        # 托管合约
│   └── Stake.sol         # 质押合约
│
├── infra/
│   ├── docker/           # Docker 配置
│   ├── k8s/              # Kubernetes 配置
│   ├── cloudrun/         # Google Cloud Run
│   └── cloudflare/       # Cloudflare Pages
│
├── docs/                 # 文档
│   └── CHECKPOINTS/      # 开发检查点
│
└── .github/workflows/    # CI/CD
```

## 快速开始

### 环境要求

- Python 3.11+
- SQLite3

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/yurimeng/DCM.git
cd DCM

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python scripts/init_db.py

# 启动服务
uvicorn src.main:app --reload
```

### 运行测试

```bash
# 运行所有测试
pytest tests/

# 测试特定模块
pytest tests/unit/test_p2p/
pytest tests/unit/test_worker_pool/

# 带覆盖率
pytest tests/ --cov=src --cov-report=html
```

### 环境变量

```bash
# 复制示例环境变量文件
cp .env.example .env

# 编辑 .env 配置你的参数
```

## API 文档

服务启动后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 主要端点

| 模块 | 端点 | 说明 |
|------|------|------|
| Jobs | `POST /api/v1/jobs` | 提交任务 |
| Jobs | `GET /api/v1/jobs/{id}` | 获取任务状态 |
| Nodes | `POST /api/v1/nodes/register` | 注册节点 |
| Workers | `POST /api/v1/workers/register` | 注册 Worker |
| Workers | `GET /api/v1/workers/select` | 选择 Worker |
| Cluster | `GET /api/v1/cluster/status` | 集群状态 |
| P2P | `GET /api/v1/p2p/status` | P2P 网络状态 |

## 区块链集成

### 合约

- `contracts/Escrow.sol` - USDC 托管合约
- `contracts/Stake.sol` - 节点质押合约

### 部署

```bash
cd contracts
npm install
npx hardhat run scripts/deploy_contracts.js --network mumbai
```

### 配置

```bash
# 环境变量
ETH_RPC_URL=https://rpc-mumbai.maticvigil.com
PRIVATE_KEY=your_key
ESCROW_CONTRACT_ADDRESS=0x...
STAKE_CONTRACT_ADDRESS=0x...
USE_BLOCKCHAIN=true
```

## 部署

### Docker

```bash
docker-compose up -d
```

### Cloud Run (Google Cloud)

```bash
./scripts/deploy-cloudrun.sh
```

### Cloudflare Pages

```bash
wrangler pages deploy
```

## 约束规则 (红线)

| 规则 | 描述 |
|------|------|
| DCM-01 | Stake 必须存在于链上合约，不能进入系统账户 |
| DCM-02 | 不能人工指定节点，Router 撮合不可干预 |
| DCM-03 | Layer 1 验证必须在线 |
| DCM-04 | 争议处理：冻结不扣除，Buyer 不获补偿 |

## 相关文档

- **PRD**: `DCM/docs/PRD/`
- **功能规格**: `DCM/docs/Function/`
- **检查点**: `DCM/docs/CHECKPOINTS/`
- **开发指南**: `DCM/DEVELOPMENT.md`

## License

MIT License

---

*文档位置: Obsidian Vault `DCM/`*
