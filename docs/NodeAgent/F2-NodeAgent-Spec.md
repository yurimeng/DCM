"""
F2-NodeAgent: 节点客户端软件规范
================================

> 版本: 3.1
> 优先级: P0
> 状态: 已实现

---

## 一、功能概述

Node Agent 是运行在 Seller 节点上的客户端软件，负责：
1. 连接 Router 注册节点信息
2. 拉取待执行 Job
3. 调用本地 LLM（Ollama）执行推理
4. 提交执行结果
5. 保持心跳，报告健康状态

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                      Node Agent                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Router    │  │   Ollama    │  │   Heartbeat        │  │
│  │   Client    │  │   Client    │  │   Manager          │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│         └────────────────┴─────────────────────┘             │
│                          │                                   │
│                  ┌───────┴───────┐                          │
│                  │  Result       │                          │
│                  │  Submitter    │                          │
│                  └───────────────┘                          │
└─────────────────────────────────────────────────────────────┘
                          │
                    WebSocket / HTTP
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      Router Service                          │
│                  (DCM Backend: src/main.py)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、通信协议

### 协议选择策略

| 场景 | 推荐协议 | 说明 |
|------|---------|------|
| 实时性要求高 | WebSocket | Router 主动推送 Job |
| 网络不稳定 | HTTP Polling | 节点定期拉取 |
| 防火墙限制 | HTTP Polling | WebSocket 被阻断时降级 |

### WebSocket 连接

```
WebSocket URL: ws://{router_host}:{router_port}/ws/nodes/{node_id}
```

**消息格式（JSON）：**

```json
// 节点 → Router: 注册
{
  "type": "register",
  "node_id": "uuid-xxx",
  "capabilities": {
    "models": ["qwen2.5:7b", "qwen3.5:latest"],
    "max_concurrent": 4
  }
}

// Router → 节点: Job 推送
{
  "type": "job_assigned",
  "match_id": "uuid-yyy",
  "job": {
    "job_id": "uuid-zzz",
    "model": "qwen2.5:7b",
    "input_tokens": 2048,
    "output_tokens_limit": 1024,
    "max_latency": 5000,
    "locked_price": 0.30
  }
}

// 节点 → Router: 心跳
{
  "type": "heartbeat",
  "timestamp": 1712841600000,
  "status": "idle"
}

// Router → 节点: 心跳响应
{
  "type": "heartbeat_ack",
  "timestamp": 1712841600000
}
```

---

## 四、Ollama 集成

### 支持版本

- Ollama **0.1.25+**
- 支持模型：`qwen2.5:7b`, `qwen3.5:latest`, `gemma4:e4b` 等

### Ollama API 调用

```python
# Ollama Generate API
POST http://localhost:11434/api/generate

Request:
{
  "model": "qwen2.5:7b",
  "prompt": "<input_tokens decoded>",
  "options": {
    "num_predict": 1024,  # output_tokens_limit
    "temperature": 0.7
  },
  "stream": false
}

Response:
{
  "response": "<output_text>",
  "done": true,
  "total_duration": 3200000000,  # nanoseconds
  "eval_count": 856  # output token count
}
```

---

## 五、Node Agent 状态机

```
DISCONNECTED → CONNECTING → IDLE → PROCESSING
                  │                       │
                  │                       ▼
                  │                   COMPLETED → IDLE
                  │                       │
                  │                       ▼
                  └─────────────────→ ERROR → IDLE
                                               │
                                               ▼
                                         DISCONNECTED
```

| 状态 | 含义 | 可接收 Job |
|------|------|-----------|
| DISCONNECTED | 未连接 Router | ❌ |
| CONNECTING | 正在连接 | ❌ |
| IDLE | 已连接，等待 Job | ✅ |
| PROCESSING | 正在执行推理 | ❌ |
| COMPLETED | 结果已提交 | ✅ |
| ERROR | 执行出错 | ⚠️ 等待重试 |

---

## 六、Job 执行流程

```
1. 接收 Job (WebSocket / Polling)
   ↓
2. 解码 input_tokens (base64 → UTF-8)
   ↓
3. 调用 Ollama 执行推理
   ↓
4. 获取 result + eval_count + total_duration
   ↓
5. 计算 SHA256(result)
   ↓
6. 提交结果到 Router
   ↓
7. 等待验证结果（可选）
```

---

## 七、Node_ID 管理 (v3.1 增强)

### 7.1 生成规则
- Node_ID 必须自动生成（UUID）
- 不可自定义
- 首次注册后持久化到本地文件

### 7.2 持久化存储
```python
# 本地文件
.node_id      # 存储 Node_ID
.node_info    # 存储节点能力信息
```

### 7.3 恢复流程
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

## 八、心跳机制

### 心跳间隔

- **默认：** 30 秒
- **执行中：** 保持连接，不发送心跳
- **超时：** Router 60 秒无心跳视为掉线

### 心跳消息

```json
{
  "type": "heartbeat",
  "node_id": "uuid-xxx",
  "status": "idle" | "processing",
  "current_job_id": "uuid-yyy" | null,
  "timestamp": 1712841600000
}
```

---

## 九、配置参数

```yaml
# node_agent.yaml

router:
  host: "localhost"
  port: 8000
  use_websocket: true  # false 则降级为 HTTP polling
  poll_interval: 5      # 秒（HTTP 模式）
  reconnect_interval: 10  # 秒
  max_retries: 3

ollama:
  host: "localhost"
  port: 11434
  models:
    - "qwen2.5:7b"
    - "qwen3.5:latest"
  timeout: 60  # 秒

agent:
  node_id: ""  # 注册后填充
  heartbeat_interval: 30  # 秒
  max_concurrent_jobs: 4  # v3.1 支持多并发

logging:
  level: "INFO"
  file: "node_agent.log"
```

---

## 十、API 接口依赖

| 操作 | Router API | 说明 |
|------|-----------|------|
| 注册节点 | POST /api/v1/nodes | 首次启动 |
| 上线 | POST /api/v1/nodes/{id}/online | Stake 确认后 |
| 拉取 Job | POST /api/v1/nodes/{id}/poll | HTTP 模式 |
| 提交结果 | POST /api/v1/nodes/{id}/jobs/{job_id}/result | 执行完成 |
| 心跳 | POST /api/v1/nodes/{id}/heartbeat | HTTP 模式 |

---

## 十一、错误处理

| 错误类型 | 处理方式 | 重试 |
|---------|---------|------|
| Ollama 无响应 | 标记失败，返回 error | ❌ |
| Ollama 超时 | 标记超时，返回 latency_exceeded | ❌ |
| 网络断开 | 重连 + 重新拉取 | ✅ |
| 结果提交失败 | 重试 3 次，间隔 5s | ✅ |
| Token 超限 | 返回实际 token 数 | ❌ |

---

## 十二、实现清单

- [x] Node_ID 自动生成
- [x] Node_ID 本地持久化
- [x] metadata 扩展字段
- [x] 心跳同步到 matching_service
- [x] Slot 概念支持
- [x] Multi-Job 并发支持
- [x] WebSocket/HTTP 双协议

---

## 十三、相关文档

- [[DCM-v3.1-Architecture]] - 核心架构
- [[DCM-v3.1-PreLock-Mechanism]] - Pre-Lock 机制
- [[F3-Match-Engine-2.0]] - Match Engine 规范

---

## 十四、后续扩展

- [ ] 多模型支持
- [ ] GPU 利用率监控
- [ ] WebSocket TLS 加密
- [ ] 本地 tokenizer
- [ ] 批量 Job 处理

"""

# 文件位置: DCM/docs/NodeAgent/F2-NodeAgent-Spec.md
