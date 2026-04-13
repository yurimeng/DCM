# F14: QUIC Transport

> **优先级**: P0
> **状态**: 待开发
> **来源**: 网络架构设计讨论
> **前置依赖**: F13 Core P2P Network

---

## 功能概述

推理数据的可靠传输层，基于 HTTP/3 (QUIC)，负责 Node/Worker 与 Core 之间的推理请求和结果传输。

---

## 通信分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DCM 网络分层                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [Buyer] ────────── HTTPS ──────────▶ [Router]                     │
│                                              │                      │
│                                              │ HTTPS                │
│                                              ▼                      │
│                                       [Core Cluster]                │
│                                        (3 nodes)                    │
│                                              │                      │
│                       ┌─────────────────────┼─────────────────────┐│
│                       │ P2P (libp2p)       │ QUIC (HTTP3)       ││
│                       ▼                     ▼                     ││
│                 [Core-2] ◄── Relay ────▶ [Core-3]                 │
│                       │                                             │
│                       │ QUIC                                        │
│                       ▼                                             │
│                 [Worker Pool]                                      │
│                       │                                             │
│                       │ QUIC (推理数据)                             │
│                       ▼                                             │
│                 [Node Agent]                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 技术选型

| 考量 | 分析 | 决策 |
|------|------|------|
| 协议 | HTTP/3 over QUIC | 复用 HTTP 语义，streaming 原生支持 |
| 0-RTT | QUIC 1-RTT + 0-RTT on resumption | 冷启动优化 |
| 丢包处理 | QUIC 内置 FEC（可选）| MVP 关闭，降低复杂度 |
| 流控 | QUIC 流级流控 | 单连接多流复用 |
| 拥塞控制 | CUBIC / BBR | 可配置，默认 CUBIC |

**注意**：推理框架侧（vLLM/TGI）HTTP/3 client 支持情况需 Dev 确认。

---

## 推理数据流

```
推理请求流程：

1. Router 收到 Buyer 的 Job
   → F3 撮合匹配 Node
   → Router 通过 HTTP/3 发送 prompt 到 Node

2. Node 执行推理
   → 流式返回 result tokens
   → Router 通过 HTTP/3 streaming 转发给 Buyer

3. 推理完成后
   → Node 返回 result_hash + actual_latency
   → Router 触发 F5 验证
```

---

## 接口设计

### 14.1 推理请求（HTTP/3）

```
POST /api/v1/inference/execute
Headers:
  Content-Type: application/json
  X-Job-ID: job-xxx
  X-Match-ID: match-xxx
  X-Request-Type: inference
Body:
{
  "model": "qwen2.5:7b",
  "prompt": "你好，请介绍一下自己",
  "max_tokens": 256,
  "temperature": 0.7
}

Response (streaming):
Content-Type: text/event-stream
X-Result-Hash: 0xabc123...
X-Latency-Ms: 3200

data: {"token": "你好"}
data: {"token": "，"}
data: {"token": "我是"}
...
data: [DONE]
```

### 14.2 推理状态查询

```
GET /api/v1/inference/status/{job_id}

Response:
{
  "job_id": "job-xxx",
  "status": "streaming",  // queued | processing | streaming | completed | failed
  "tokens_received": 128,
  "tokens_expected": 256,
  "latency_ms": 2100
}
```

### 14.3 推理结果确认

```
POST /api/v1/inference/confirm
Body:
{
  "job_id": "job-xxx",
  "result_hash": "0xabc123...",
  "actual_latency_ms": 3200
}

Response:
{
  "confirmed": true,
  "verification_triggered": true
}
```

---

## 数据模型

### InferenceRequest

```python
class InferenceRequest:
    job_id: str
    match_id: str
    model: str              # "qwen2.5:7b"
    prompt: str
    max_tokens: int
    temperature: float
    stream: bool = True
    timeout_ms: int = 30000
```

### InferenceResult

```python
class InferenceResult:
    job_id: str
    result_hash: str        # SHA256(prompt + result)
    actual_latency_ms: int
    tokens_generated: int
    streaming_complete: bool
    error: str | None
```

---

## 性能目标

| 指标 | 目标 | 说明 |
|------|------|------|
| 端到端延迟 | < 10s | 满足 MVP 成功标准 |
| 首 token 延迟 | < 2s | QUIC 0-RTT 优化 |
| 吞吐量 | > 50 MB/s | 千兆网络下 |
| 连接建立 | < 50ms | 已有连接复用 |

---

## 与现有模块关系

| 关系 | 说明 |
|------|------|
| F3 撮合引擎 | 撮合后 Router 通过 F14 发送推理请求 |
| F5 验证服务 | F14 返回 result_hash 触发 F5 验证 |
| F13 Core P2P | F14 在 Core 内部通过 P2P 连接传输（QUIC over libp2p）|

---

## Worker/Node 侧需求

| 组件 | 需求 | 备注 |
|------|------|------|
| HTTP/3 Server | Node Agent 内置 或 sidecar | 监听 443/UDP |
| TLS 证书 | 节点证书（noise 协议生成）| 复用 F13 身份 |
| 推理框架 | vLLM/TGI HTTP inference | 需要 HTTP/3 支持 |

**Dev 需要确认**：现有推理框架是否支持 HTTP/3？如不支持，是改造框架还是加 HTTP/3 proxy？

---

## 验收标准

- [ ] HTTP/3 连接建立 < 50ms
- [ ] streaming 推理结果实时转发
- [ ] result_hash 在推理完成后 100ms 内返回
- [ ] 与现有 HTTPS Router 兼容（通过 Core 协议转换）
- [ ] 满足 F8 定义的 < 10s 端到端延迟要求
