# DCM v3.1 文档库

> 分布式计算市场 (Distributed Compute Marketplace) 规范文档

---

## 📁 文档结构

```
docs/
├── Architecture/              # 核心架构文档
│   ├── DCM-v3.1-Architecture.md        # 系统架构
│   └── DCM-v3.1-PreLock-Mechanism.md   # Pre-Lock 机制
│
├── Function/                 # 功能模块规范
│   └── F3-Match-Engine-2.0.md         # Match Engine 2.0
│
├── NodeAgent/               # Node Agent 规范
│   └── F2-NodeAgent-Spec.md            # Node Agent 完整规范
│
└── TEST/                    # 测试报告
    └── TEST-REPORT-2026-04-13.md      # 测试报告
```

---

## 📖 核心文档

| 文档 | 描述 | 状态 |
|------|------|------|
| [[DCM-v3.1-Architecture]] | 系统架构、层级关系、执行链路 | ✅ |
| [[DCM-v3.1-PreLock-Mechanism]] | Pre-Lock 机制、多 Job 并发 | ✅ |
| [[F3-Match-Engine-2.0]] | Match Engine 规范、F3.1-F3.8 | ✅ |
| [[F2-NodeAgent-Spec]] | Node Agent 规范、通信协议 | ✅ |
| [[TEST-REPORT-2026-04-13]] | 测试报告 | ✅ |

---

## 🏗️ 层级架构

```
Level 1: SLOT        (Market Trading Unit)
Level 2: NODE        (Resource Container)
Level 3: WORKER      (Execution Scheduler)
Level 4: RUNTIME     (Inference Engine)
Level 5: MODEL       (LLM Weights)
```

---

## 🔗 关键机制

### Pre-Lock 机制 (v3.1)

```
Match Engine Select Slot
         ↓
SlotPreLock Request (TTL: 5000ms)
         ↓
SlotPreLock Ack
         ↓
Slot Reserve (HARD_LOCK)
         ↓
Dispatch → Worker Execute
         ↓
SlotRelease → FREE
```

### 模型兼容性

| 类型 | Score | 条件 |
|------|-------|------|
| EXACT | 1.0 | 完全匹配 |
| FAMILY | 0.8 | 版本/Size 覆盖 |
| COMPATIBLE | 0.6 | 兼容模型 |
| CROSS_FAMILY | 0.3 | 跨家族 |
| INVALID | 0.0 | 不兼容 |

---

## 🚀 快速链接

- **测试报告**: [[TEST-REPORT-2026-04-13]]
- **架构文档**: [[DCM-v3.1-Architecture]]
- **Match Engine**: [[F3-Match-Engine-2.0]]
- **Node Agent**: [[F2-NodeAgent-Spec]]

---

## 📊 版本信息

| 版本 | 日期 | 主要更新 |
|------|------|----------|
| 3.0 | 2026-04-12 | 基础 Match Engine |
| 3.1 | 2026-04-13 | Pre-Lock 机制、多 Job 并发 |

---

**最后更新**: 2026-04-13
