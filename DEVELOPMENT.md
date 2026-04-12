# DCM MVP 开发计划

> 基于 PRD 0.2 & Function 定义

---

## 一、项目进度

| Sprint | 状态 | 测试数 | 覆盖率 |
|--------|------|--------|--------|
| Sprint 0: 基础设施 | ✅ | 14 | 47% |
| Sprint 1: API + 数据库 | ✅ | 15 | 65% |
| Sprint 2: 核心业务逻辑 | ✅ | 19 | 67% |
| Sprint 3: Node Agent SDK | ✅ | 14 | 62% |
| **Mock Wallet + Cloudflare** | ✅ | 14 | 64% |
| Sprint 5: 测试 + 部署 | 🔴 | - | - |
| Sprint 6: 链上集成 | 🔴 | - | - |

---

## 二、快速开始

### 1. 启动服务

```bash
# Docker (推荐)
docker-compose up -d

# 或直接运行
pip install -r requirements.txt
uvicorn src.main:app --reload
```

### 2. 初始化测试钱包

```bash
curl -X POST http://localhost:8000/api/v1/wallet/initialize
```

### 3. 测试 API

```bash
# 查看账户
curl http://localhost:8000/api/v1/wallet/accounts

# 提交 Job
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3-8b",
    "input_tokens": 2048,
    "output_tokens_limit": 1024,
    "max_latency": 5000,
    "bid_price": 0.35
  }'
```

### 4. 查看文档

```
http://localhost:8000/docs
```

---

## 三、API 端点

### Wallet API (`/api/v1/wallet`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/wallet/initialize` | POST | 初始化测试账户 |
| `/wallet/accounts` | GET | 列出账户 |
| `/wallet/accounts/{id}` | GET | 账户详情 |
| `/wallet/accounts/{id}/balance` | GET | 余额 |
| `/wallet/escrow/lock` | POST | Escrow 锁定 |
| `/wallet/escrow/settle` | POST | Escrow 结算 |

### Jobs API (`/api/v1/jobs`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/jobs` | POST | 创建 Job |
| `/jobs/{id}` | GET | 详情 |
| `/jobs/{id}/escrow` | GET | Escrow 状态 |

### Nodes API (`/api/v1/nodes`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/nodes` | POST | 注册节点 |
| `/nodes/{id}/poll` | POST | 拉取 Job |
| `/nodes/{id}/stake/deposit` | POST | Stake 存款 |

---

## 四、部署

### Cloudflare

```bash
# 构建并推送
docker build -t dcm-api .
docker tag dcm-api ghcr.io/your-username/dcm-api:latest
docker push ghcr.io/your-username/dcm-api:latest

# 部署
cf deploy ghcr.io/your-username/dcm-api:latest
```

详细文档: [docs/Cloudflare-Deployment.md](docs/Cloudflare-Deployment.md)

---

## 五、测试

```bash
# 运行所有测试
pytest tests/ -v

# 带覆盖率
pytest tests/ --cov=src --cov-report=html

# 只运行单元测试
pytest tests/unit/ -v
```

---

## 六、目录结构

```
DCM/
├── src/
│   ├── api/           # API 路由
│   ├── core/          # 核心逻辑 (wallet)
│   ├── services/      # 业务服务
│   ├── models/        # 数据模型
│   └── agents/        # Node Agent SDK
├── tests/             # 测试
├── docs/              # 文档
├── scripts/           # 脚本
├── .cloudflare/       # Cloudflare 配置
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 七、下一步

1. **Sprint 5**: 集成测试 + 部署
2. **链上集成**: 替换 Mock Wallet 为真实合约
