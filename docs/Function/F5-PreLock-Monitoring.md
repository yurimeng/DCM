# F5 - Pre-lock 心跳监控测试报告

> **日期**: 2026-04-14
> **功能**: 心跳监控 + Pre-lock 状态跟踪

---

## 1. 功能概述

### 1.1 心跳响应结构

```json
{
  "node_id": "60092aa0-88bd-4473-a458-c32270e408f9",
  "status": "idle",
  "timestamp": 1776098918557,
  "matched": true,
  "re_register": false,
  "pre_lock_jobs": [],
  "pre_lock_count": 0
}
```

### 1.2 Pre-lock Jobs 详情

```json
{
  "pre_lock_jobs": [
    {
      "job_id": "job_xxx",
      "prompt": "...",
      "model": "qwen2.5:7b",
      "pre_lock_expires_at": "2026-04-13T16:00:00.000000"
    }
  ]
}
```

---

## 2. 测试结果

### 2.1 心跳监控

| 指标 | 结果 |
|------|------|
| 心跳间隔 | 30 秒 |
| 日志频率 | 每 3 次心跳 (~90 秒) |
| 状态显示 | ✅ |
| matched 显示 | ✅ |
| pre_lock_count | ✅ |

### 2.2 心跳日志

```
💓 心跳 #3 | status=idle | matched=True | pre_lock=0
💓 心跳 #6 | status=idle | matched=True | pre_lock=0
```

### 2.3 Job 处理统计

| 指标 | 结果 |
|------|------|
| Job 处理 | 8 个 |
| 结果提交 | 8 个 |
| 成功率 | 100% |

---

## 3. Pre-lock 机制分析

### 3.1 Job 状态流转

```
created → pending → matched → pre_locked → reserved → dispatched → running → finished
```

### 3.2 当前状态

| 状态 | 说明 |
|------|------|
| MATCHED | ✅ 已实现 |
| PRE_LOCKED | ⚠️ Slot 层面预留，Job 层面未触发 |

### 3.3 Pre-lock 说明

- **Slot Pre-lock**: 在 Slot 层面预留资源，TTL 后自动释放
- **Job Pre-lock**: 目前 Job 直接从 MATCHED 进入处理流程，未触发 PRE_LOCKED 状态

---

## 4. 云端 API 修改

### 4.1 心跳响应 (nodes.py)

```python
# 获取 Pre-lock Jobs
pre_lock_jobs = []
pre_locked_jobs = db.query(JobDB).filter(
    JobDB.node_id == node_id,
    JobDB.status == JobStatusDB.PRE_LOCKED
).all()

for job in pre_locked_jobs:
    pre_lock_jobs.append({
        "job_id": job.job_id,
        "prompt": job.prompt,
        "model": job.model,
        "pre_lock_expires_at": job.pre_lock_expires_at.isoformat() if job.pre_lock_expires_at else None,
    })

return {
    "pre_lock_jobs": pre_lock_jobs,
    "pre_lock_count": len(pre_lock_jobs),
}
```

---

## 5. Node Agent 修改

### 5.1 心跳监控

```python
# 记录心跳数据 (每 3 次心跳记录一次)
self._heartbeat_count = getattr(self, '_heartbeat_count', 0) + 1
if self._heartbeat_count % 3 == 0:
    logger.info(f"💓 心跳 #{self._heartbeat_count} | status={node_status} | matched={matched} | pre_lock={pre_lock_count}")
    
    if pre_lock_jobs:
        for job in pre_lock_jobs:
            logger.info(f"📌 Pre-lock: {job['job_id'][:12]}... | prompt={job.get('prompt', 'N/A')[:20]}...")
```

---

## 6. 结论

| 功能 | 状态 |
|------|------|
| 心跳监控 | ✅ 完成 |
| Pre-lock 状态跟踪 | ✅ 完成 |
| Pre-lock 触发 | ⚠️ 需进一步实现 |

### 后续计划

1. [ ] 实现 Job 层面的 Pre-lock 触发
2. [ ] 添加 Pre-lock ACK 机制
3. [ ] 实现 Pre-lock 超时处理
