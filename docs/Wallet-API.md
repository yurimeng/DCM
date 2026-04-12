# Wallet API - 模拟钱包

> 用于测试环境的链上账户模拟

---

## 概述

Mock Wallet Service 模拟链上钱包操作，用于：
- 本地测试（无需真实链上交互）
- 集成测试
- 演示和 POC

---

## API 端点

### 初始化

```
POST /api/v1/wallet/initialize
```

创建预设测试账户：
- `buyer-001` / `buyer-002` / `buyer-003` - 各 100 USDC
- `node-001` / `node-002` / `node-003` - 各 50 USDC
- `system` - 系统账户（手续费）

---

### 账户管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/wallet/accounts` | POST | 创建账户 |
| `/api/v1/wallet/accounts` | GET | 列出账户 |
| `/api/v1/wallet/accounts/{id}` | GET | 获取账户 |
| `/api/v1/wallet/accounts/{id}/balance` | GET | 获取余额 |
| `/api/v1/wallet/accounts/{id}/transactions` | GET | 交易历史 |

---

### 转账

```
POST /api/v1/wallet/transfer

Body:
{
  "from_account_id": "buyer-001",
  "to_account_id": "node-001",
  "amount": 10.0,
  "memo": "Test transfer"
}
```

---

### Escrow 操作

```
POST /api/v1/wallet/escrow/lock     # 锁定资金
POST /api/v1/wallet/escrow/release  # 释放（退款）
POST /api/v1/wallet/escrow/settle   # 结算
```

---

### Stake 操作

```
POST /api/v1/wallet/stake/deposit?account_id=node-001&amount=50.0
```

---

## 使用示例

### 1. 初始化钱包

```bash
curl -X POST http://localhost:8000/api/v1/wallet/initialize
```

Response:
```json
{
  "initialized": true,
  "accounts": {
    "buyer-001": {
      "account_id": "buyer-001",
      "address": "0x...",
      "balance": 100.0,
      "role": "buyer"
    },
    ...
  }
}
```

### 2. 创建 Job 并锁定 Escrow

```bash
# 1. 创建 Job
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3-8b",
    "input_tokens": 2048,
    "output_tokens_limit": 1024,
    "max_latency": 5000,
    "bid_price": 0.35
  }'

# 2. 锁定 Escrow
curl -X POST http://localhost:8000/api/v1/wallet/escrow/lock \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_id": "buyer-001",
    "amount": 0.001,
    "job_id": "<job-id>"
  }'
```

### 3. 结算

```bash
curl -X POST http://localhost:8000/api/v1/wallet/escrow/settle \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "<job-id>",
    "buyer_id": "buyer-001",
    "node_id": "node-001",
    "node_amount": 0.00095,
    "platform_amount": 0.00005
  }'
```

### 4. 查询余额

```bash
curl http://localhost:8000/api/v1/wallet/accounts/buyer-001/balance
curl http://localhost:8000/api/v1/wallet/accounts/node-001/balance
```

---

## 与 Job 流程集成

```
1. Buyer 提交 Job
   ↓
2. 系统锁定 Escrow（模拟）
   POST /wallet/escrow/lock
   ↓
3. 撮合 → Node 执行
   ↓
4. 验证通过 → 结算
   POST /wallet/escrow/settle
   (node ← 95%, system ← 5%)
   ↓
5. 验证失败 → 退款
   POST /wallet/escrow/release
```

---

## 统计

```
GET /api/v1/wallet/stats

{
  "total_accounts": 7,
  "by_role": {
    "buyer": 3,
    "node": 3,
    "system": 1
  },
  "total_balance": 450.0,
  "total_staked": 0
}
```

---

## 测试账户

| ID | 角色 | 初始余额 | 用途 |
|----|------|---------|------|
| buyer-001 | Buyer | 100 USDC | 测试 Buyer 操作 |
| buyer-002 | Buyer | 100 USDC | 测试 Buyer 操作 |
| buyer-003 | Buyer | 100 USDC | 测试 Buyer 操作 |
| node-001 | Node | 50 USDC | 测试 Node 操作 |
| node-002 | Node | 50 USDC | 测试 Node 操作 |
| node-003 | Node | 50 USDC | 测试 Node 操作 |
| system | System | 0 USDC | 手续费收取 |

---

## 注意事项

1. **测试环境专用** - 此服务仅用于测试，不应用于生产
2. **内存存储** - 每次重启数据丢失
3. **无加密签名** - 简化测试用
4. **可扩展** - 可替换为真实链上交互
