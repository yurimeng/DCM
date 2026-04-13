---
title: Function 模块索引
date: 2026-04-13
updated: 2026-04-13
tags:
  - DCM
  - Function
  - Index
---

# Function 模块索引

> 来源：[[PRD 0.1：Decentralized Compute Market — MVP定义稿（修订版）]]

---

## 模块总览

| 模块编号 | 模块名称 | 优先级 | 状态 | 章节来源 |
|---------|---------|-------|------|---------|
| [[F1: Job 提交与管理系统]] | Demand Side | P0 | ✅ 完成 | 三、2 & 四、4.1 |
| [[F2: 节点注册与状态管理]] | Supply Side | P0 | ✅ 完成 | 三、1 & 四、4.2 |
| [[F3: 撮合引擎]] | Market Layer | P0 | ✅ 完成 | 五、5.1 |
| [[F4: 失败重试机制]] | Market Layer | P0 | ✅ 完成 | 五、5.4 |
| [[F5: 验证服务]] | Market Layer | P0 | ✅ 完成 | 五、5.2 |
| [[F6: 结算服务]] | Market Layer | P0 | ✅ 完成 | 五、5.5 |
| [[F7: Stake 管理与争议处理]] | Market Layer | P1 | ⚠️ 部分 | 五、5.3 |
| [[F8: 技术架构与数据流]] | 基础设施 | P0 | ✅ 完成 | 十、10.1 & 10.2 |
| [[F9: Core Cluster]] | 基础设施 | P0 | 📋 待开发 | 十、10.1 |
| [[F10: Scaler]] | 扩缩容 | P0 | 📋 待开发 | 十、10.1 |
| [[F11: Worker Pool]] | 扩缩容 | P0 | 📋 待开发 | 十、10.1 |
| [[F12: 链上账本集成]] | 账本 | P0 | 📋 待开发 | R-008d |
| [[F13: Core P2P Network]] | 网络 | P0 | 📋 待开发 | 网络架构讨论 |
| [[F14: QUIC Transport]] | 网络 | P0 | 📋 待开发 | 网络架构讨论 |
| [[F15: Relay Service]] | 网络 | P0 | 📋 待开发 | 网络架构讨论 |

---

## 依赖关系图

```
F1 Job提交
  └── F3 撮合引擎（触发）
  └── F6 结算服务（触发）
  └── F11 Worker Pool（处理）

F2 节点注册
  └── F7 Stake管理（前置）

F3 撮合引擎
  └── F1 Job提交（输入）
  └── F2 节点状态（输入）
  └── F5 验证服务（触发）
  └── F9 Core Cluster（DNS路由）

F4 失败重试
  └── F3 撮合引擎（触发）

F5 验证服务
  └── F3 撮合引擎（触发）
  └── F7 Stake冻结（触发）

F6 结算服务
  └── F5 验证通过（触发）
  └── F4 失败重试（触发）
  └── F12 链上账本（同步）

F7 Stake管理与争议
  └── F5 验证异常（触发）

F9 Core Cluster
  └── F1-F6 业务逻辑
  └── F12 链上账本

F10 Scaler
  └── F9 Core Cluster（监控）
  └── F11 Worker Pool（控制）

F11 Worker Pool
  └── F9 Core Cluster（状态同步）
  └── F10 Scaler（调度）

F12 链上账本集成
  └── F6 结算服务（触发）
  └── Escrow.sol（链上）

F13 Core P2P Network
  └── F9 Core Cluster（通信底层）
  └── F15 Relay Service（relay 客户端）

F14 QUIC Transport
  └── F13 Core P2P Network（传输通道）
  └── F3 撮合引擎（触发推理请求）
  └── F5 验证服务（返回 result_hash）

F15 Relay Service
  └── F13 Core P2P Network（relay 协议栈）
  └── F9 Core Cluster（Relay 节点兼任）
```

---

## 网络模块（F13-F15）

> 2026-04-13 网络架构设计讨论后新增

### 通信分层架构

```
[Buyer] ──HTTPS──▶ [Router] ──HTTPS──▶ [Core Cluster]
                                          │
                    ┌─────────────────────┼────────────────────┐
                    │ P2P优先+Relay兜底  │ QUIC(HTTP3)       │
                    ▼                     ▼
              [Core-2] ◄──Relay──────▶ [Core-3]
                    │
                    │ QUIC (推理数据)
                    ▼
              [Worker Pool]
```

### 通信分层

| 通信场景 | 协议 | 功能模块 |
|---------|------|---------|
| Buyer → Router | HTTPS | - |
| Router ↔ Core | HTTPS | - |
| Core ↔ Core | P2P (libp2p + gossipsub) | F13 |
| 推理数据传输 | QUIC (HTTP/3) | F14 |
| Worker ↔ Core | QUIC (HTTP/3) | F14 |
| 直连失败时 | Relay (libp2p circuit v2) | F15 |

### 技术选型汇总

| 层次 | 技术 | 模块 |
|------|------|------|
| P2P 框架 | libp2p (golang) | F13 |
| pub/sub | gossipsub | F13 |
| 推理传输 | HTTP/3 (QUIC) | F14 |
| Relay 协议 | libp2p circuit relay v2 | F15 |
| 传输加密 | noise + TLS 1.3 | F13 |
| 身份标识 | peer_id (libp2p) | F13 |

---

## 待处理（P0前置条件）

上线前必须完成的事情（来自 PRD 第九节）：

- **Q1**: Layer 2 相似度阈值校准（100+ 真实 Job 基准测试）
- **Q2**: Stake 门槛确认（5-10 个目标节点访谈）
- **Q3**: Core Cluster 高可用验证
- **Q4**: Scaler 扩缩阈值调优

