"""
DCM v3.1 Slot Pre-Lock 机制规范
=================================

> 版本: 3.1
> 状态: 已实现
> 更新: 2026-04-13

---

## 一、核心原则

1. **1 Slot** = 并发执行 Job 的逻辑容器
2. **1 Worker** = 实际调度执行单元
3. **1 Node** = Slot + Worker 资源池
4. **Pre-Lock** = 防止多 Job 抢占冲突的短期资源预占

---

## 二、Slot 多 Job 承载模型

### 2.1 并发结构

```json
{
  "slot_id": "slot_001",
  "worker_id": "worker_001",
  "capacity": {
    "max_concurrency": 4,
    "active_jobs": 2,
    "reserved_jobs": 1,
    "pre_locked_jobs": 1
  },
  "job_sets": {
    "reserved": ["job_101"],
    "running": ["job_102", "job_103"],
    "queued": ["job_104"]
  }
}
```

### 2.2 并发规则

```
active_jobs + reserved_jobs + pre_locked_jobs ≤ max_concurrency
```

---

## 三、Slot 状态模型

| 状态 | 条件 | 描述 |
|------|------|------|
| FREE | 无任何 Job | 完全可用 |
| PRE_LOCKED | 有未确认的 Pre-Lock | 等待 Ack |
| PARTIALLY_RESERVED | 1 ≤ reserved < max | 部分预约 |
| FULLY_RESERVED | reserved = max | 容量满 |
| RUNNING | active_jobs > 0 | 正在执行 |
| OVERLOADED | 超负载 | 异常状态 |
| FAILED | 执行失败 | 异常状态 |

---

## 四、Job 状态扩展

```python
class JobStatus(str, Enum):
    CREATED = "created"           # 已创建
    PENDING = "pending"          # 已提交，等待撮合
    MATCHED = "matched"          # 已匹配
    PRE_LOCKED = "pre_locked"    # 预锁定中
    RESERVED = "reserved"       # 已预约
    DISPATCHED = "dispatched"    # 已分发
    RUNNING = "running"          # 执行中
    COMPLETED = "completed"      # 完成
    FAILED = "failed"           # 失败
    CANCELLED = "cancelled"      # 取消
```

---

## 五、Pre-Lock 生命周期

```
PENDING
    ↓
MATCHED
    ↓
PRE_LOCKED (TTL: 5000ms)
    ↓ (Ack)
RESERVED
    ↓
DISPATCHED
    ↓
RUNNING
    ↓
RELEASED → FREE
```

### 状态转换时间线

| 阶段 | 状态 | TTL | 说明 |
|------|------|-----|------|
| 匹配成功 | MATCHED | - | 选择最优 Slot |
| 资源预占 | PRE_LOCKED | 5000ms | 防止抢占 |
| 确认预约 | RESERVED | - | Pre-Lock Ack |
| 分发执行 | DISPATCHED | - | 发送到 Worker |
| 实际运行 | RUNNING | - | 推理执行中 |
| 完成释放 | RELEASED | - | 资源释放 |

---

## 六、Pre-Lock 请求/响应

### 6.1 Pre-Lock 请求

```json
{
  "event": "SlotPreLock",
  "job_id": "job_001",
  "slot_id": "slot_001",
  "ttl_ms": 5000
}
```

### 6.2 Pre-Lock Ack

```json
{
  "event": "SlotPreLockAck",
  "job_id": "job_001",
  "slot_id": "slot_001",
  "status": "locked",
  "expires_at": 1710000005000
}
```

### 6.3 Pre-Lock Reject

```json
{
  "event": "SlotPreLockReject",
  "job_id": "job_001",
  "slot_id": "slot_001",
  "reason": "capacity_full"
}
```

---

## 七、Slot Lock 模型

### 7.1 Lock Table

```python
class SlotLock(BaseModel):
    job_id: str           # Job ID
    lock_type: LockType   # PRE_LOCK / HARD_LOCK / RUNNING
    expires_at: Optional[int]  # TTL 过期时间戳
    created_at: int       # 创建时间
```

### 7.2 Lock 类型

| 类型 | 描述 | TTL | 容量占用 |
|------|------|-----|---------|
| PRE_LOCK | 临时预占 | 5000ms | ✓ |
| HARD_LOCK | 已分配 | 无 | ✓ |
| RUNNING | 执行中 | 无 | ✓ |

---

## 八、容量管理

### 8.1 容量字段

```python
class CapacityInfo(BaseModel):
    max_concurrency: int = 1        # 最大并发
    active_jobs: int = 0            # 运行中
    reserved_jobs: int = 0           # 已预约
    pre_locked_jobs: int = 0         # 预锁定
```

### 8.2 可用容量计算

```python
@property
def available_capacity(self) -> int:
    return max(0, self.max_concurrency - 
               (self.active_jobs + 
                self.reserved_jobs + 
                self.pre_locked_jobs))
```

---

## 九、Pre-Lock + Dispatch 完整流程

```
1. JobCreate
   ↓
2. Match Engine Select Slot
   ↓
3. SlotPreLock Request
   ↓
4. SlotPreLockAck / Reject
   ↓
5. PreLock Confirmed
   ↓
6. SlotReserve (HARD_LOCK)
   ↓
7. SlotDispatch
   ↓
8. Node → Worker Queue
   ↓
9. Worker Execute
   ↓
10. SlotRelease
```

---

## 十、失败处理

### 10.1 Slot Full

```
解决方案: re-match next slot
```

### 10.2 TTL Expired

```
触发: now > expires_at
处理: release lock → retry match
```

### 10.3 Node Failure

```
触发: Node 无响应
处理: failover to backup slot
```

---

## 十一、关键设计决策

1. **Pre-Lock TTL**: 5000ms（足够完成 Ack 往返）
2. **容量检查时机**: Pre-Lock 请求时
3. **锁类型分离**: PRE_LOCK（临时）/ HARD_LOCK（确认）
4. **状态自动更新**: 根据 capacity 实时计算 Slot 状态

---

## 十二、代码示例

```python
# Pre-Lock 请求
slot.pre_lock("job_001", ttl_ms=5000)

# Pre-Lock 确认
slot.confirm_pre_lock("job_001")

# 开始执行
slot.start_running("job_001")

# 完成释放
slot.finish_job("job_001")
```

---

## 十三、测试覆盖

| 测试 | 场景 | 状态 |
|------|------|------|
| test_prelock_basic | 基础流程 | ✅ |
| test_prelock_expire | TTL 过期 | ✅ |
| test_prelock_multi | 多 Job 预占 | ✅ |
| test_e2e_match_with_pre_lock | E2E 匹配 | ✅ |
| test_e2e_multi_job_match | 多 Job 并发 | ✅ |

"""

# 文件位置: DCM/docs/Architecture/DCM-v3.1-PreLock-Mechanism.md
