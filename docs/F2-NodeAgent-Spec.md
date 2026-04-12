# F2-NodeAgent: 节点客户端软件规范

> 来源：PRD 九、Q3 & F2 节点注册与状态管理
> 优先级：P0
> 状态：规范定义中

---

## 功能概述

Node Agent 是运行在 Seller 节点上的客户端软件，负责：
1. 连接 Router 注册节点信息
2. 拉取待执行 Job
3. 调用本地 LLM（Ollama）执行推理
4. 提交执行结果
5. 保持心跳，报告健康状态

---

## 架构总览

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
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      Router Service                          │
│                  (DCM Backend: src/main.py)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 通信协议

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

**连接流程：**
1. 节点建立 WebSocket 连接
2. 发送注册消息（node_id + capabilities）
3. Router 返回确认消息
4. 保持连接，接收 Job 推送或心跳响应

**消息格式（JSON）：**
```json
// 节点 → Router: 注册
{
  "type": "register",
  "node_id": "uuid-xxx",
  "capabilities": {
    "models": ["llama3-8b"],
    "max_concurrent": 1
  }
}

// Router → 节点: Job 推送
{
  "type": "job_assigned",
  "match_id": "uuid-yyy",
  "job": {
    "job_id": "uuid-zzz",
    "model": "llama3-8b",
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

### HTTP Polling（降级模式）

```
Poll URL: POST /api/v1/nodes/{node_id}/poll
Heartbeat URL: POST /api/v1/nodes/{node_id}/heartbeat
```

**轮询间隔：** 默认 5 秒，可配置

---

## Ollama 集成

### 支持版本

- Ollama **0.1.25+**
- 支持模型：`llama3-8b`

### Ollama API 调用

```python
# Ollama Generate API
POST http://localhost:11434/api/generate

Request:
{
  "model": "llama3-8b",
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

### Token 编码

MVP 阶段使用简单编码（UTF-8 bytes → token 近似）：
```python
def estimate_tokens(text: str) -> int:
    """估算 token 数量（简化版）"""
    return len(text.encode('utf-8')) // 4
```

> ⚠️ 正式版应使用 tiktoken 或等效 tokenizer

---

## Node Agent 状态机

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
| DISCONNECTED | 连接断开 | ❌ |

---

## Job 执行流程

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
   POST /api/v1/nodes/{node_id}/jobs/{job_id}/result
   {
     "result": "<base64_encoded>",
     "result_hash": "sha256:...",
     "actual_latency_ms": 3200,
     "actual_output_tokens": 856
   }
   ↓
7. 等待验证结果（可选）
```

---

## 心跳机制

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

## 错误处理

### 错误类型与重试

| 错误类型 | 处理方式 | 重试 |
|---------|---------|------|
| Ollama 无响应 | 标记失败，返回 error | ❌ |
| Ollama 超时 | 标记超时，返回 latency_exceeded | ❌ |
| 网络断开 | 重连 + 重新拉取 | ✅ |
| 结果提交失败 | 重试 3 次，间隔 5s | ✅ |
| Token 超限 | 返回实际 token 数 | ❌ |

### 错误消息格式

```json
{
  "type": "job_error",
  "job_id": "uuid-xxx",
  "error_type": "ollama_error" | "timeout" | "network_error",
  "error_message": "具体错误信息",
  "timestamp": 1712841600000
}
```

---

## 配置参数

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
  model: "llama3-8b"
  timeout: 60  # 秒

agent:
  node_id: ""  # 注册后填充
  heartbeat_interval: 30  # 秒
  max_concurrent_jobs: 1  # MVP 仅支持 1

logging:
  level: "INFO"
  file: "node_agent.log"
```

---

## 安装与部署

### 环境要求

- Python 3.9+
- Ollama 0.1.25+
- 网络可达 Router

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/yurimeng/DCM.git
cd DCM/src/agents

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置
cp config.yaml.example config.yaml
# 编辑 config.yaml 填入 node_id

# 4. 启动 Ollama（后台）
ollama serve &
ollama pull llama3-8b

# 5. 启动 Node Agent
python node_agent.py
```

---

## API 接口依赖

| 操作 | Router API | 说明 |
|------|-----------|------|
| 注册节点 | POST /api/v1/nodes | 首次启动 |
| 上线 | POST /api/v1/nodes/{id}/online | Stake 确认后 |
| 拉取 Job | POST /api/v1/nodes/{id}/poll | HTTP 模式 |
| 提交结果 | POST /api/v1/nodes/{id}/jobs/{job_id}/result | 执行完成 |
| 心跳 | POST /api/v1/nodes/{id}/heartbeat | HTTP 模式 |

---

## 安全考虑

| 方面 | 措施 |
|------|------|
| 节点身份 | JWT Token 认证 |
| 结果完整性 | SHA256 哈希，Router 验证 |
| 通信安全 | HTTPS / WSS（生产环境） |
| 限流 | 每节点 10 req/s |

---

## MVP 约束

1. **单模型**：仅支持 llama3-8b
2. **单并发**：同一时间仅处理 1 个 Job
3. **简单 Token 估算**：使用 UTF-8 bytes / 4
4. **无加密**：MVP 使用明文通信（生产环境必须 TLS）

---

## 依赖关系

```
Node Agent
  ├── Ollama（执行推理）
  ├── Router API（通信）
  └── F2 节点注册 → F3 撮合 → F5 验证 → F6 结算
```

---

## 后续扩展（PRD 1.0）

- [ ] 多模型支持
- [ ] 多并发 Job
- [ ] WebSocket 加密（TLS）
- [ ] 本地 tokenizer
- [ ] 批量 Job 处理
- [ ] GPU 利用率监控
