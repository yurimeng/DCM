---
title: TODO Sprint 8 - Match Engine 2.0
type: todo
created: 2026-04-13
status: active
---

# TODO Sprint 8 - Match Engine 2.0

## 目标

实现 Match Engine 2.0，支持 Slot-based 调度和模型兼容性匹配。

## 功能清单

### F3.1 Slot 数据结构
- [ ] 创建 Slot 模型
- [ ] 创建 Model/Capacity/Pricing/Performance 信息模型
- [ ] 定义 SlotStatus 枚举
- [ ] 更新 Node Agent 支持 Slot 概念
- [ ] 测试: 本地测试 Slot 创建

### F3.2 Order Book
- [ ] 实现 OrderBook 类（按 Model Family 分桶）
- [ ] 实现 Job 添加到 Order Book
- [ ] 实现 Slot 添加到 Order Book
- [ ] 测试: 验证分桶逻辑

### F3.3 Hard Filter
- [ ] 实现状态检查
- [ ] 实现容量检查
- [ ] 实现价格检查
- [ ] 实现延迟检查
- [ ] 测试: 验证过滤条件

### F3.4 Compatibility Matrix
- [ ] 实现 Exact Match (1.0)
- [ ] 实现 Family Match (0.8)
- [ ] 实现 Compatible Match (0.6)
- [ ] 实现通用任务匹配
- [ ] 测试: 验证兼容性评分

### F3.5 Scoring Function
- [ ] 实现 PriceScore (30%)
- [ ] 实现 LatencyScore (25%)
- [ ] 实现 LoadScore (15%)
- [ ] 实现 ReputationScore (15%)
- [ ] 实现 CompatibilityScore (15%)
- [ ] 测试: 验证评分排序

### F3.6-7 Slot Lifecycle
- [ ] 实现 FREE → RESERVED
- [ ] 实现 RESERVED → RUNNING
- [ ] 实现 RUNNING → RELEASED
- [ ] 实现 Slot Release
- [ ] 测试: 验证状态流转

### E2E 测试
- [ ] 提交通用 Job（无 model）
- [ ] 提交指定模型 Job
- [ ] 验证匹配到最优 Slot
- [ ] 验证结果正确

## 里程碑

| 阶段 | 完成标准 |
|------|----------|
| Phase 1 | F3.1-F3.4 完成，基础撮合可用 |
| Phase 2 | F3.5-F3.7 完成，完整调度可用 |
| Phase 3 | E2E 测试通过 |

## 相关文档

- [[F3-Match-Engine-2.0]]
- [[DCM/Requirement/Match Engine 2.0]]
