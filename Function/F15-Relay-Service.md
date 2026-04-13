# F15: Relay Service

> **优先级**: P0
> **状态**: 待开发
> **来源**: 网络架构设计讨论
> **前置依赖**: F13 Core P2P Network

---

## 功能概述

P2P 直连的兜底机制。当节点因 NAT/防火墙无法直连时，通过 Relay 中继转发流量。Relay 节点由 Core Cluster 兼任。

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
│                                          ▲    │                     │
│                           P2P  ─────────┘    │                     │
│                              │                │                     │
│                       ┌──────┴──────┐    Relay (self)              │
│                       │             │    (Core 兼任)                │
│                       ▼             ▼                              │
│                 [Worker-A] ◄─── Relay ──► [Worker-B]               │
│              (behind NAT)                         (behind NAT)      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| Relay 协议 | libp2p circuit relay v2 | 内置支持，开箱即用 |
| Relay 节点 | Core Cluster 兼任 | 3 个 Core = 3 个 Relay 候选 |
| 连接策略 | 直连优先 → Relay 兜底 | auto relay |
| 带宽控制 | per-connection 限速 | 防止 Relay 滥用 |

---

## 连接建立策略

```
┌─────────────────────────────────────────────────────────────────┐
│                    P2P 连接建立流程                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   发起节点                                                    │
│       │                                                       │
│       ▼                                                       │
│  尝试直连 ───────────────────────────────────────┐             │
│       │                                          │             │
│       │ 成功 ──▶ 使用直连通道                    │             │
│       │                                          │             │
│       │ 失败（超时/拒绝）                        ▼             │
│       │                                    尝试 Relay         │
│       │                                          │             │
│       │  有可用 Relay ──▶  建立 relay 通道       │             │
│       │                                          │             │
│       │  无可用 Relay ──▶  返回连接失败          ▼             │
│                                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 接口设计

### 15.1 Relay 状态（运维）

```
GET /api/v1/relay/status

Response:
{
  "relay_enabled": true,
  "active_connections": 5,
  "total_bandwidth_mbps": 120.5,
  "max_connections": 1000,
  "relay_candidates": [
    "QmXYZ... (core-1)",
    "QmABC... (core-2)",
    "QmDEF... (core-3)"
  ]
}
```

### 15.2 连接诊断

```
GET /api/v1/relay/diagnostics?peer_id=QmXYZ...

Response:
{
  "peer_id": "QmXYZ...",
  "connection_type": "relayed",  // direct | relayed | failed
  "direct_attempts": 3,
  "direct_failures": 3,
  "relay_node": "QmABC... (core-2)",
  "latency_ms": 45,
  "last_error": "timeout"
}
```

---

## 带宽控制

| 角色 | 限制 | 说明 |
|------|------|------|
| 每连接 | 10 Mbps | 防止单连接占满 Relay |
| 每 Worker | 50 Mbps | Worker 带宽上限 |
| 每 Core Relay 总计 | 1 Gbps | Core 节点 Relay 上限 |
| 免费额度 | 无 | Relay 是基础设施成本 |

---

## 与现有模块关系

| 关系 | 说明 |
|------|------|
| F13 Core P2P | F15 是 F13 的 relay 组件，libp2p 内置集成 |
| F14 QUIC Transport | QUIC 流量可以通过 Relay 传输 |
| F9 Core Cluster | Core 节点兼任 Relay 节点 |

---

## 安全考量

| 方面 | 设计 |
|------|------|
| Relay 滥用 | 带宽限制 + per-connection 限速 |
| 隐私 | Relay 无法解密流量（端到端加密）|
| Relay 节点选择 | 优先选择低延迟 Core，拒绝可疑节点 |
| 成本控制 | Relay 带宽计入运营成本 |

---

## 限制与约束

| 约束 | 说明 |
|------|------|
| MVP 仅 Core Relay | 不开放外部节点作为 Relay |
| 最多 3 个 Relay | Core Cluster 节点数 |
| Relay 非永久 | 仅在直连失败时使用 |
| MVP 不计费 | Relay 带宽成本暂不向 Worker 收取 |

---

## 验收标准

- [ ] Worker 在 NAT 后能通过 Relay 连接 Core
- [ ] Relay 模式下端到端延迟增加 < 100ms
- [ ] 直连恢复后自动切换（不手动重连）
- [ ] Relay 带宽不超过 Core 节点上限
- [ ] 满足 F8 定义的 < 10s 端到端延迟要求（含 Relay）
