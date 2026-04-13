---
title: F2-NodeAgent 增强需求
type: function
module: NodeAgent
created: 2026-04-13
updated: 2026-04-13
status: implemented
---

# F2-NodeAgent 增强需求

## 1. Node_ID 持久化

### 1.1 生成规则
- Node_ID 必须自动生成（UUID）
- 不可自定义
- 首次注册后持久化到本地文件

### 1.2 持久化存储
```python
# 本地文件
.node_id      # 存储 Node_ID
.node_info    # 存储节点能力信息
```

### 1.3 恢复流程
```
Agent 启动
    ↓
加载本地 .node_id
    ↓
检查 DCM 是否存在该 Node_ID
    ├── 存在 → 使用该 Node_ID
    └── 不存在 → 注册新节点
```

---

## 2. 返回确认机制

### 2.1 绑定信息
Node_ID 应绑定以下信息：
- **Node ID**: 自动生成的 UUID
- **用户绑定**: user_id（可选，绑定钱包后填写）
- **钱包地址**: wallet_address（可选）
- **节点能力**: gpu_type, vram_gb, models, pricing
- **标签**: tags（自定义标签）

### 2.2 metadata 扩展字段
```python
metadata = {
    "user_id": None,        # 未来绑定用户
    "wallet_address": None,  # 未来绑定钱包
    "tags": [],             # 自定义标签
    "bound_at": None,       # 绑定时间
}
```

### 2.3 API 返回
注册节点时返回完整信息：
```json
{
  "node_id": "uuid",
  "status": "offline",
  "stake_required": 200.0,
  "stake_amount": 0.0,
  "next_step": "Deposit 200.0 USDC to activate",
  "metadata": {
    "user_id": null,
    "wallet_address": null,
    "tags": []
  }
}
```

---

## 3. 无匹配即注册机制

### 3.1 场景
- 数据库损坏或迁移
- Agent 心跳同步后，节点未在 matching_service 中
- 无法获取 Job

### 3.2 处理流程
```
Agent 发送心跳
    ↓
检查 matching_service 是否有该节点
    ↓
无匹配 → 注册新 Node_ID（复用原有能力信息）
    ↓
返回新 Node_ID
    ↓
保存到本地
```

### 3.3 实现逻辑
```python
def on_heartbeat_response(response):
    if response.get("node_id") != current_node_id:
        # 数据库损坏，节点不存在
        # 重新注册
        register_new_node()
        
    if response.get("re_register"):
        # 服务端要求重新注册
        register_new_node()
```

---

## 4. 状态机

```
┌─────────────────────────────────────────────────────────────┐
│                    Node Agent 状态机                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐                                               │
│  │  START   │                                               │
│  └────┬─────┘                                               │
│       │                                                     │
│       ▼                                                     │
│  ┌──────────┐    存在     ┌──────────┐                     │
│  │ LOAD     │───────────▶│ ONLINE   │                     │
│  │ (加载ID) │             │ (已注册) │                     │
│  └────┬─────┘             └─────┬────┘                     │
│       │ 不存在                  │                          │
│       ▼                         │ 无法匹配                   │
│  ┌──────────┐                   │                          │
│  │ REGISTER │───────────────────┘                          │
│  │ (注册)   │                                            │
│  └────┬─────┘                                            │
│       │                                                    │
│       ▼                                                    │
│  ┌──────────┐                                             │
│  │ WAIT     │◀────────────────────────────────┐           │
│  │ (等待确认) │                                 │           │
│  └────┬─────┘                                  │           │
│       │ 收到确认                               │心跳超时    │
│       ▼                                        │           │
│  ┌──────────┐                                 │           │
│  │ ONLINE   │─────────────────────────────────┘           │
│  │ (上线)   │                                              │
│  └────┬─────┘                                              │
│       │                                                     │
│       ▼                                                     │
│  ┌──────────┐     收到 Job    ┌──────────┐               │
│  │ POLLING  │───────────────▶│ WORKING │               │
│  │ (轮询)   │◀───────────────│ (工作中) │               │
│  └──────────┘     完成        └──────────┘               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. API 端点

### 5.1 注册节点
```
POST /api/v1/nodes
```

Request:
```json
{
  "gpu_type": "NVIDIA RTX 4090",
  "vram_gb": 24,
  "model_support": ["qwen2.5:7b"],
  "ask_price": 0.002,
  "avg_latency": 100,
  "region": "us-west"
}
```

Response:
```json
{
  "node_id": "uuid",
  "status": "offline",
  "stake_required": 200.0,
  "stake_amount": 0.0,
  "next_step": "Deposit 200.0 USDC to activate",
  "metadata": {
    "user_id": null,
    "wallet_address": null,
    "tags": []
  }
}
```

### 5.2 心跳
```
POST /api/v1/nodes/{node_id}/heartbeat
```

Response:
```json
{
  "node_id": "uuid",
  "status": "online",
  "matched": true,
  "re_register": false
}
```

---

## 6. 实现清单

- [x] Node_ID 自动生成
- [x] Node_ID 本地持久化
- [x] metadata 扩展字段
- [x] 心跳同步到 matching_service
- [ ] 无匹配时返回 re_register 标志
- [ ] 心跳响应中包含绑定确认

---

## 7. 相关文档

- [[F2-NodeAgent-Spec]] - Node Agent 基础规范
- [[F3-Matching]] - 撮合引擎
