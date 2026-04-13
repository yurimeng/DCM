# DCM v3.1 文档库

> 分布式计算市场 (Distributed Compute Marketplace) 规范文档
> 
> ⚠️ **所有过程文档已迁移到 Obsidian Vault: YurimengKB/DCM/**

---

## 📁 Obsidian Vault 文档结构

```
YurimengKB/
└── DCM/
    ├── docs/                      # 架构与设计文档
    │   ├── DCM-v3.0-Architecture.md
    │   ├── DCM-v3.1-Architecture.md           ← 核心架构
    │   ├── DCM-v3.1-PreLock-Mechanism.md     ← Pre-Lock 机制
    │   └── TEST-REPORT-2026-04-13.md         ← 测试报告
    │
    ├── Function/                  # 功能模块规范
    │   ├── F2-NodeAgent-Spec.md               ← Node Agent
    │   └── F3-Match-Engine-2.0.md             ← Match Engine
    │
    └── ... (其他目录)
```

---

## 🔗 快速链接 (Obsidian Vault)

| 文档 | Vault 路径 |
|------|-----------|
| 核心架构 v3.1 | [[DCM/docs/DCM-v3.1-Architecture]] |
| Pre-Lock 机制 | [[DCM/docs/DCM-v3.1-PreLock-Mechanism]] |
| Match Engine 2.0 | [[DCM/Function/F3-Match-Engine-2.0]] |
| Node Agent 规范 | [[DCM/Function/F2-NodeAgent-Spec]] |
| 测试报告 | [[DCM/docs/TEST-REPORT-2026-04-13]] |

---

## 📝 文档规范

### 命名规则
- 架构文档: `DCM-vX.Y-功能名.md`
- 功能规范: `FX-功能名.md`
- 测试报告: `TEST-REPORT-YYYY-MM-DD.md`

### 归档规则
- 所有过程文档 → Obsidian Vault
- 本地保留: 代码、配置、构建产物

---

**最后更新**: 2026-04-13
