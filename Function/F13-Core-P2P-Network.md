# F13: Core P2P Network

> **优先级**: P0
> **状态**: 待开发
> **来源**: 网络架构设计讨论
> **前置依赖**: F9 Core Cluster

---

## 功能概述

Core Cluster 3节点间的 P2P 通信层，实现节点发现、状态广播和数据同步。底层使用 libp2p，拓扑为全互联。

---

## 通信分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DCM 网络分层                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [Buyer] ────────── HTTPS ──────────▶ [Router]                    │
│                                              │                      │
│                                              │ HTTPS                │
│                                              ▼                      │
│                                       [Core Cluster]                │
│                                        (3 nodes)                    │
│                                              │                      │
│                       ┌─────────────────────┼─────────────────────┐│
│                       │ P2P (libp2p/gossipsub)  │ QUIC (HTTP3)    ││
│                       ▼                       ▼                   ││
│                 [Core-2] ◄──── Relay ────▶ [Core-3]                │
│                       │                                             │
│                       │ QUIC (推理数据)                              │
│                       ▼                                             │
│                 [Worker Pool]                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 技术选型

| 层次 | 技术 | 说明 |
|------|------|------|
| P2P 框架 | libp2p (golang) | NAT 穿透、relay、加密内置 |
| 节点发现 | mDNS + bootstrap list | Core 节点固定 IP，互为 bootstrap |
| pub/sub | gossipsub | Core 间状态广播（job 更新、节点状态）|
| 传输加密 | noise + TLS 1.3 | 双向证书认证 |
| 身份标识 | peer_id (libp2p) | 基于公钥的不可伪造身份 |

---

## 接口设计

### 13.1 节点信息

```
GET /api/v1/p2p/info

Response:
{
  "peer_id": "QmXYZ...",
  "addresses": [
    "/ip4/1.2.3.4/tcp/4001/p2p/QmXYZ...",
    "/ip6/::1/tcp/4001/p2p/QmXYZ..."
  ],
  "connected_peers": 2,
  "relay_enabled": true
}
```

### 13.2 连接状态

```
GET /api/v1/p2p/connections

Response:
{
  "peers": [
    {
      "peer_id": "QmABC...",
      "address": "core-2.dcm.io",
      "direction": "outbound",
      "latency_ms": 5,
      "status": "connected"
    },
    {
      "peer_id": "QmDEF...",
      "address": "core-3.dcm.io",
      "direction": "outbound",
      "latency_ms": 8,
      "status": "connected"
    }
  ],
  "relays_in_use": 0
}
```

### 13.3 P2P 广播（内部）

```
// gossipsub topic: job_updates
{
  "type": "job_update",
  "job_id": "job-xxx",
  "status": "completed",
  "timestamp": 1713000000,
  "source_peer": "QmXYZ..."
}
```

---

## 数据模型

### PeerInfo

```python
class PeerInfo:
    peer_id: str          # libp2p 生成的基于公钥的 ID
    addresses: List[str]   # 多地址列表
    is_relay: bool        # 是否为 Relay 候选节点
    last_seen: datetime
    latency_ms: float
    connection_count: int
```

### GossipMessage

```python
class GossipMessage:
    topic: str            # 'job_updates' | 'node_status' | 'escrow_sync'
    source_peer: str
    data: dict
    timestamp: int
    sequence_num: int      # 防重复
```

---

## 协议栈

```
┌─────────────────────────────────┐
│  Application: gossipsub         │  ← 状态广播
├─────────────────────────────────┤
│  P2P: libp2p (golang)           │  ← 节点发现、relay
├─────────────────────────────────┤
│  Transport: TCP + QUIC           │  ← 连接传输
├─────────────────────────────────┤
│  Security: noise + TLS 1.3      │  ← 加密认证
└─────────────────────────────────┘
```

---

## 节点发现策略

```
启动流程：
1. 从配置文件加载 bootstrap 节点列表（另外 2 个 Core 节点地址）
2. 尝试连接 bootstrap 节点
3. 连接成功 → 获取 peer table → 建立全互联
4. 连接失败 → 记录错误 → 重试（指数退避）

重连策略：
- 心跳间隔：30s
- 节点超时：90s 无响应 → 断开并重连
- 重连上限：5 次后标记为不可达
```

---

## 与现有模块关系

| 关系 | 说明 |
|------|------|
| F9 Core Cluster | F13 是 F9 的通信底层，F9 调用 F13 的广播能力 |
| F3 撮合引擎 | 撮合结果通过 gossipsub 广播给所有 Core |
| F12 链上账本 | 链上同步结果通过 gossipsub 广播 |
| F15 Relay | F13 内置 relay 客户端，需要 F15 的 relay 服务 |

---

## 安全考量

| 方面 | 设计 |
|------|------|
| 节点认证 | libp2p TLS 双向证书 |
| 消息完整性 | gossipsub 签名验证 |
| 抗审查 | 节点可配置 topic 过滤 |
| DoS 防护 | 限速：每秒最多 100 条 gossip |

---

## 验收标准

- [ ] 3 个 Core 节点启动后自动建立全互联 P2P 连接
- [ ] job_update 消息在 100ms 内广播到所有 Core
- [ ] 节点断连后自动重连（90s 内恢复）
- [ ] relay 模式下消息延迟 < 500ms
- [ ] 满足 F8 定义的 < 10s 端到端延迟要求
