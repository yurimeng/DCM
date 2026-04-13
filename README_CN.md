# DCM - 去中心化计算市场

> Decentralized Compute Marketplace
> 
> **版本**: v3.1 | **状态**: MVP (验证阶段)

---

## 概述

DCM 是一个**全球去中心化 AI 推理市场**，让任何人都能参与 GPU 算力交易。

### MVP 验证目标

| 验证领域 | 成功标准 |
|----------|----------|
| **技术** | Job 完整流程：提交 → 执行 → 结果 → 结算 |
| **市场** | 价格由市场机制形成，而非预设 |
| **经济** | 节点运营商有收益，买家比中心化 API 更省钱 |

---

## 核心特性

- **Slot 匹配**: 高效资源分配，支持 Pre-Lock 机制
- **模型兼容性**: 多模型家族支持，兼容性评分
- **多 Job 并发**: 单 Slot 支持最多 4 个并发任务
- **区块链结算**: Polygon 上的 USDC Escrow 和 Stake 管理
- **P2P 网络**: 基于 QUIC 传输的去中心化通信
- **自动扩缩**: 动态 Worker Pool 管理

---

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        API 层 (FastAPI)                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │   Jobs   │  │  Nodes   │  │  Wallet  │  │ Disputes │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       └────────────┴────────────┴────────────┘             │
│                          │                                  │
│       ┌───────────────────┴───────────────────┐            │
│       │          Core Cluster (F9)             │            │
│       │  ┌──────────┐  ┌──────────┐            │            │
│       │  │ Scaler   │──│  Worker  │            │            │
│       │  │  (F10)   │  │  Pool    │            │            │
│       │  └──────────┘  │  (F11)   │            │            │
│       │                └────┬─────┘            │            │
│       │                     │                  │            │
│       └─────────────────────┼──────────────────┘            │
│                             │                               │
│       ┌─────────────────────┼─────────────────────┐         │
│       │        网络层 (F13-F15)                    │         │
│       │  ┌────────┐  ┌────────┐  ┌────────┐      │         │
│       │  │  P2P   │──│  QUIC  │──│ Relay  │      │         │
│       │  │ (F13)  │  │ (F14)  │  │ (F15)  │      │         │
│       │  └────────┘  └────────┘  └────────┘      │         │
│       └──────────────────────────────────────────┘         │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                    服务层 (F1-F7)                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │   撮合引擎   │  │   验证服务  │  │   结算服务  │             │
│  └────────────┘  └────────────┘  └────────────┘             │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                  区块链 (Polygon Amoy)                        │
│  ┌────────────┐  ┌────────────┐                             │
│  │   Escrow   │  │   Stake    │                             │
│  │   合约     │  │   合约     │                             │
│  └────────────┘  └────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 项目结构

```
DCM/
├── src/
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置管理
│   ├── database.py          # 数据库初始化
│   │
│   ├── api/                 # API 路由
│   │   ├── jobs.py          # Job 提交 (F1)
│   │   ├── nodes.py         # 节点注册 (F2)
│   │   ├── disputes.py      # 争议处理 (F7)
│   │   ├── wallet.py        # 钱包操作
│   │   ├── core.py          # Core Cluster (F9)
│   │   ├── scaler.py        # Scaler 服务 (F10)
│   │   ├── worker_pool.py   # Worker Pool (F11)
│   │   ├── p2p.py           # P2P 网络 (F13)
│   │   ├── quic.py          # QUIC 传输 (F14)
│   │   ├── relay.py         # Relay 服务 (F15)
│   │   └── internal.py      # 内部 API
│   │
│   ├── services/            # 业务逻辑 (F1-F7)
│   │   ├── match_engine_v2.py    # 撮合引擎 2.0 (F3)
│   │   ├── order_book.py         # 订单簿
│   │   ├── compatibility.py      # 模型兼容性
│   │   ├── hard_filter.py        # 硬过滤器
│   │   ├── scoring.py            # 评分函数
│   │   ├── pre_lock.py           # Pre-Lock 机制
│   │   ├── verification.py       # 验证服务 (F5)
│   │   ├── escrow.py             # Escrow 服务 (F6)
│   │   ├── stake.py              # Stake 管理 (F7)
│   │   ├── retry.py              # 重试机制 (F4)
│   │   └── chain_sync.py         # 区块链同步
│   │
│   ├── core/                 # 核心基础设施
│   │   ├── cluster/          # Core Cluster 服务
│   │   ├── p2p/              # P2P 网络 (F13)
│   │   ├── quic/             # QUIC 传输 (F14)
│   │   └── relay/            # Relay 服务 (F15)
│   │
│   ├── models/               # 数据模型
│   ├── agents/               # Node Agent 客户端
│   └── web3/                 # 区块链集成
│
├── tests/                    # 测试套件
│   ├── test_phase1.py        # 阶段1：核心模型
│   ├── test_phase2.py        # 阶段2：核心服务
│   ├── test_phase3_e2e.py    # 阶段3：E2E 测试
│   ├── test_local_comprehensive.py
│   └── test_ollama_integration.py
│
├── contracts/                # 区块链合约
│   ├── Escrow.sol
│   └── Stake.sol
│
├── docs/                     # 文档
├── Function/                 # 功能规范
├── Requirement/              # 需求文档
└── Architecture/            # 架构文档
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| API 层 | FastAPI (Python 3.11+) |
| 数据库 | SQLite (MVP) |
| 结算链 | Polygon Amoy (USDC) |
| 验证 | SHA256 + ROUGE-L |
| 节点通信 | WebSocket + HTTP |
| P2P 网络 | 自定义 asyncio + QUIC |

---

## 快速开始

### 前置条件

- Python 3.11+
- SQLite3
- Ollama (本地推理)

### 安装

```bash
# 克隆仓库
git clone https://github.com/yurimeng/DCM.git
cd DCM

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动 Ollama（另一个终端）
ollama serve
ollama pull qwen2.5:7b

# 启动 DCM API
uvicorn src.main:app --reload --port 8000
```

### 运行测试

```bash
# 所有测试
pytest tests/ -v

# 分阶段测试
pytest tests/test_phase1.py -v
pytest tests/test_phase2.py -v
pytest tests/test_phase3_e2e.py -v

# 带覆盖率
pytest tests/ --cov=src --cov-report=html
```

---

## 核心模块

### 撮合引擎 2.0 (F3)

| 功能 | 说明 |
|------|------|
| Slot 结构 | 包含模型、容量、定价的交易单元 |
| Order Book | 按模型家族分桶 |
| Hard Filter | 兼容性 + 容量 + 价格 + 延迟 |
| 兼容性矩阵 | EXACT=1.0, FAMILY=0.8, COMPATIBLE=0.6 |
| 评分函数 | 价格(30%) + 延迟(25%) + 负载(15%) + 声誉(15%) + 兼容(15%) |
| **Pre-Lock** | 5000ms TTL 预锁定，防止冲突 |

### Node Agent

| 功能 | 说明 |
|------|------|
| 协议 | WebSocket (主) + HTTP Polling (备) |
| 注册 | 自动生成 UUID，本地持久化 |
| 心跳 | 30s 间隔，60s 超时 |
| 多 Job | 每 Slot 最多 4 个并发任务 |
| Ollama 集成 | 支持 v0.1.25+ |

---

## 配置项

`config.py` 中的关键配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `mvp_model` | qwen2.5:7b | 支持的模型 |
| `platform_fee_rate` | 0.05 | 5% 平台费 |
| `layer2_sample_rate` | 0.1 | 10% 验证抽样 |
| `heartbeat_timeout_seconds` | 30 | 节点超时阈值 |
| `escrow_buffer` | 1.1 | 1.1x Escrow 倍数 |

---

## API 接口

| 模块 | 端点 | 方法 | 说明 |
|------|------|------|------|
| Jobs | `/api/v1/jobs` | POST | 提交 Job |
| Jobs | `/api/v1/jobs/{id}` | GET | 获取 Job 状态 |
| Jobs | `/api/v1/jobs/{id}/result` | POST | 提交结果 |
| Nodes | `/api/v1/nodes/register` | POST | 注册节点 |
| Nodes | `/api/v1/nodes/{id}/poll` | GET | 轮询 Job |
| Nodes | `/api/v1/nodes/{id}/heartbeat` | POST | 发送心跳 |
| Workers | `/api/v1/workers/register` | POST | 注册 Worker |
| Cluster | `/api/v1/cluster/status` | GET | Cluster 状态 |
| Scaler | `/api/v1/scaler/status` | GET | Scaler 状态 |
| P2P | `/api/v1/p2p/status` | GET | P2P 网络状态 |

---

## 区块链集成

### 合约

- `Escrow.sol` - Job 支付的 USDC Escrow
- `Stake.sol` - 节点 Stake 管理

### 部署

```bash
cd contracts
npm install
npx hardhat run scripts/deploy_contracts.js --network polygon_amoy
```

### 环境变量

```bash
ETH_RPC_URL=https://polygon-amoy.g.alchemy.com/v2/YOUR_KEY
PRIVATE_KEY=your_private_key
USE_BLOCKCHAIN=true
```

---

## 核心设计约束

| 规则 | 说明 |
|------|------|
| DCM-01 | Stake 必须在链上合约中，绝不在系统账户 |
| DCM-02 | 不能手动选择节点，所有匹配通过 Router |
| DCM-03 | Layer 1 验证 (SHA256) 必须在线 |
| DCM-04 | 争议处理：冻结但不扣除，不赔偿买家 |

---

## 文档

- **架构文档**: `Architecture/DCM-v3.1-Architecture.md`
- **撮合引擎**: `Function/F3-Match-Engine-2.0.md`
- **Node Agent**: `Function/F2-NodeAgent-Spec.md`
- **完整文档**: Obsidian Vault `YurimengKB/DCM/`

---

## 许可证

MIT License
