"""
Slot Models - DCM v3.1
Slot = 可交易计算能力单元 + Multi-Job 并发支持 + Pre-Lock 机制

核心特性:
1. Slot 可并发执行多个 Job (max_concurrency)
2. Pre-Lock 短期资源预占机制
3. Job Sets: reserved, running, queued
4. Lock 类型: pre_lock, hard_lock, running
"""

from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
import uuid
import time


class SlotStatus(str, Enum):
    """Slot 状态 (DCM v3.1)
    
    状态转换:
    FREE → PRE_LOCKED → RESERVED → DISPATCHED → RUNNING → RELEASED
    """
    FREE = "free"               # 可用，等待匹配
    PRE_LOCKED = "pre_locked"   # 预锁定中（等待 Pre-Lock Ack）
    PARTIALLY_RESERVED = "partially_reserved"  # 部分预约
    FULLY_RESERVED = "fully_reserved"          # 完全预约
    RESERVED = "reserved"       # 已被 Job 预约
    DISPATCHED = "dispatched"   # 已分发到 Worker
    RUNNING = "running"         # 正在执行 Job
    RELEASED = "released"       # 执行完成，释放资源
    OVERLOADED = "overloaded"   # 超负载
    FAILED = "failed"           # 执行失败


class LockType(str, Enum):
    """Lock 类型"""
    PRE_LOCK = "pre_lock"       # 临时预占（TTL 后释放）
    HARD_LOCK = "hard_lock"     # 已分配执行
    RUNNING = "running"         # 正在执行


class JobSet(BaseModel):
    """Job 集合"""
    reserved: List[str] = Field(default_factory=list, description="已预约的 Job IDs")
    running: List[str] = Field(default_factory=list, description="正在运行的 Job IDs")
    queued: List[str] = Field(default_factory=list, description="排队的 Job IDs")


class SlotLock(BaseModel):
    """Slot Lock 记录"""
    job_id: str = Field(..., description="Job ID")
    lock_type: LockType = Field(..., description="Lock 类型")
    expires_at: Optional[int] = Field(None, description="过期时间戳（毫秒）")
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))


class ModelInfo(BaseModel):
    """模型信息"""
    family: str = Field(..., description="模型族，如 qwen, llama, gemma")
    name: str = Field(..., description="模型名，如 qwen3-8b")


class CapacityInfo(BaseModel):
    """容量信息 (DCM v3.1)
    
    并发执行规则: active_jobs + reserved_jobs ≤ max_concurrency
    """
    max_concurrency: int = Field(default=1, ge=1, description="最大并发数")
    active_jobs: int = Field(default=0, ge=0, description="当前活跃 Job 数 (running)")
    reserved_jobs: int = Field(default=0, ge=0, description="已预约 Job 数 (reserved)")
    pre_locked_jobs: int = Field(default=0, ge=0, description="已预锁定 Job 数 (pre_lock)")
    
    @property
    def total_jobs(self) -> int:
        """总 Job 数 (confirmed + pre_locked)"""
        return self.active_jobs + self.reserved_jobs + self.pre_locked_jobs
    
    @property
    def available_capacity(self) -> int:
        """可用容量"""
        return max(0, self.max_concurrency - self.total_jobs)
    
    @property
    def is_full(self) -> bool:
        """是否已满"""
        return self.total_jobs >= self.max_concurrency


class PricingInfo(BaseModel):
    """定价信息"""
    input_price: float = Field(..., gt=0, description="输入 token 单价 (USDC/1M tokens)")
    output_price: float = Field(..., gt=0, description="输出 token 单价 (USDC/1M tokens)")


class PerformanceInfo(BaseModel):
    """性能信息"""
    avg_latency_ms: int = Field(default=0, ge=0, description="平均延迟 (ms)")
    success_rate: float = Field(default=0.95, ge=0, le=1, description="成功率 (0-1)")
    p50_latency_ms: int = Field(default=0, ge=0, description="P50 延迟 (ms)")
    p95_latency_ms: int = Field(default=0, ge=0, description="P95 延迟 (ms)")


class Slot(BaseModel):
    """Slot 可交易计算能力单元 (DCM v3.1)
    
    Slot 是 DCM v3.1 的核心交易单元，支持:
    1. Multi-Job 并发执行
    2. Pre-Lock 预占机制
    3. Job Sets 管理
    
    层级关系:
    Node → Worker → Slot → Model
    """
    slot_id: str = Field(default_factory=lambda: f"slot_{uuid.uuid4().hex[:8]}")
    node_id: str = Field(..., description="所属节点 ID")
    worker_id: str = Field(..., description="所属 Worker ID")
    
    # 模型与性能
    model: ModelInfo = Field(..., description="模型信息")
    capacity: CapacityInfo = Field(default_factory=CapacityInfo, description="容量信息")
    pricing: PricingInfo = Field(..., description="定价信息")
    performance: PerformanceInfo = Field(default_factory=PerformanceInfo, description="性能信息")
    
    # 状态
    status: SlotStatus = Field(default=SlotStatus.FREE, description="Slot 状态")
    
    # Job Sets (DCM v3.1)
    job_sets: JobSet = Field(default_factory=JobSet, description="Job 集合")
    
    # Pre-Lock 管理 (DCM v3.1)
    locks: List[SlotLock] = Field(default_factory=list, description="当前 Locks")
    
    # 兼容性 (保留旧字段)
    current_job_id: Optional[str] = Field(default=None, description="当前 Job ID (兼容)")
    
    # 元数据
    region: Optional[str] = Field(default=None, description="区域")
    created_at: int = Field(default_factory=lambda: 0, description="创建时间戳")
    updated_at: int = Field(default_factory=lambda: 0, description="更新时间戳")
    
    def is_available(self) -> bool:
        """检查 Slot 是否可用 (DCM v3.1: 允许 FREE, PRE_LOCKED, PARTIALLY_RESERVED)"""
        if self.status not in [SlotStatus.FREE, SlotStatus.PRE_LOCKED, SlotStatus.PARTIALLY_RESERVED]:
            return False
        return self.capacity.available_capacity > 0
    
    def get_pre_lock(self, job_id: str) -> Optional[SlotLock]:
        """获取 Job 的 Pre-Lock"""
        for lock in self.locks:
            if lock.job_id == job_id and lock.lock_type == LockType.PRE_LOCK:
                return lock
        return None
    
    def pre_lock(self, job_id: str, ttl_ms: int = 5000) -> bool:
        """创建 Pre-Lock
        
        Args:
            job_id: Job ID
            ttl_ms: TTL 毫秒
            
        Returns:
            是否成功
        """
        # 检查容量
        if self.capacity.available_capacity <= 0:
            return False
        
        # 检查是否已有该 Job 的 lock
        if self.get_pre_lock(job_id):
            return False
        
        now_ms = int(time.time() * 1000)
        lock = SlotLock(
            job_id=job_id,
            lock_type=LockType.PRE_LOCK,
            expires_at=now_ms + ttl_ms,
        )
        self.locks.append(lock)
        
        # 更新容量
        self.capacity.pre_locked_jobs += 1
        
        # 状态变为 PRE_LOCKED
        if self.status == SlotStatus.FREE:
            self.status = SlotStatus.PRE_LOCKED
        
        return True
    
    def pre_lock_expired(self, job_id: str) -> bool:
        """检查 Pre-Lock 是否过期"""
        lock = self.get_pre_lock(job_id)
        if not lock:
            return False
        
        now_ms = int(time.time() * 1000)
        if lock.expires_at and now_ms > lock.expires_at:
            return True
        return False
    
    def confirm_pre_lock(self, job_id: str) -> bool:
        """确认 Pre-Lock 转换为 Hard Lock
        
        Args:
            job_id: Job ID
            
        Returns:
            是否成功
        """
        lock = self.get_pre_lock(job_id)
        if not lock:
            return False
        
        # 移除 pre_lock，添加 hard_lock
        self.locks = [l for l in self.locks if not (l.job_id == job_id and l.lock_type == LockType.PRE_LOCK)]
        
        hard_lock = SlotLock(
            job_id=job_id,
            lock_type=LockType.HARD_LOCK,
        )
        self.locks.append(hard_lock)
        
        # 添加到 reserved
        if job_id not in self.job_sets.reserved:
            self.job_sets.reserved.append(job_id)
        
        # 更新容量: pre_locked -> reserved
        self.capacity.pre_locked_jobs = max(0, self.capacity.pre_locked_jobs - 1)
        self.capacity.reserved_jobs += 1
        
        # 更新状态
        self._update_status()
        
        # 兼容字段
        self.current_job_id = job_id
        
        return True
    
    def release_lock(self, job_id: str) -> bool:
        """释放 Lock
        
        Args:
            job_id: Job ID
            
        Returns:
            是否成功
        """
        original_len = len(self.locks)
        
        # 找到要释放的 lock 类型
        lock_to_release = None
        for lock in self.locks:
            if lock.job_id == job_id:
                lock_to_release = lock.lock_type
                break
        
        self.locks = [l for l in self.locks if l.job_id != job_id]
        
        if len(self.locks) == original_len:
            return False
        
        # 根据 lock 类型更新容量
        if lock_to_release == LockType.PRE_LOCK:
            self.capacity.pre_locked_jobs = max(0, self.capacity.pre_locked_jobs - 1)
        elif lock_to_release == LockType.HARD_LOCK:
            self.capacity.reserved_jobs = max(0, self.capacity.reserved_jobs - 1)
        elif lock_to_release == LockType.RUNNING:
            self.capacity.active_jobs = max(0, self.capacity.active_jobs - 1)
        
        # 从 job_sets 移除
        if job_id in self.job_sets.reserved:
            self.job_sets.reserved.remove(job_id)
        if job_id in self.job_sets.running:
            self.job_sets.running.remove(job_id)
        if job_id in self.job_sets.queued:
            self.job_sets.queued.remove(job_id)
        
        # 更新状态
        self._update_status()
        
        # 兼容字段
        if self.current_job_id == job_id:
            self.current_job_id = self.job_sets.running[0] if self.job_sets.running else \
                                   self.job_sets.reserved[0] if self.job_sets.reserved else None
        
        return True
    
    def start_running(self, job_id: str) -> bool:
        """开始运行 Job
        
        Args:
            job_id: Job ID
            
        Returns:
            是否成功
        """
        if job_id not in self.job_sets.reserved:
            return False
        
        # 移动到 running
        self.job_sets.reserved.remove(job_id)
        self.job_sets.running.append(job_id)
        
        # 更新容量
        self.capacity.reserved_jobs = max(0, self.capacity.reserved_jobs - 1)
        self.capacity.active_jobs += 1
        
        # 添加 running lock
        self.locks = [l for l in self.locks if not (l.job_id == job_id and l.lock_type == LockType.HARD_LOCK)]
        running_lock = SlotLock(
            job_id=job_id,
            lock_type=LockType.RUNNING,
        )
        self.locks.append(running_lock)
        
        # 更新状态
        self._update_status()
        
        # 兼容字段
        self.current_job_id = job_id
        
        return True
    
    def finish_job(self, job_id: str) -> bool:
        """完成 Job
        
        Args:
            job_id: Job ID
            
        Returns:
            是否成功
        """
        return self.release_lock(job_id)
    
    def _update_status(self) -> None:
        """根据当前状态更新 Slot 状态"""
        # 优先检查 RUNNING
        if self.capacity.active_jobs > 0:
            self.status = SlotStatus.RUNNING
        elif self.capacity.reserved_jobs >= self.capacity.max_concurrency:
            self.status = SlotStatus.FULLY_RESERVED
        elif self.capacity.reserved_jobs > 0:
            self.status = SlotStatus.PARTIALLY_RESERVED
        else:
            self.status = SlotStatus.FREE
    
    def reset_to_free(self) -> None:
        """重置为 FREE"""
        self.status = SlotStatus.FREE
        self.current_job_id = None
        self.locks = []
        self.job_sets = JobSet()
        self.capacity.reserved_jobs = 0
        self.capacity.active_jobs = 0
    
    def mark_failed(self) -> None:
        """标记为失败"""
        self.status = SlotStatus.FAILED
        self.current_job_id = None
    
    def cleanup_expired_locks(self) -> List[str]:
        """清理过期的 Pre-Locks
        
        Returns:
            被清理的 Job IDs
        """
        expired_jobs = []
        for lock in self.locks[:]:
            if lock.lock_type == LockType.PRE_LOCK and lock.expires_at:
                now_ms = int(time.time() * 1000)
                if now_ms > lock.expires_at:
                    expired_jobs.append(lock.job_id)
                    self.locks.remove(lock)
                    self.capacity.pre_locked_jobs = max(0, self.capacity.pre_locked_jobs - 1)
        
        # 如果没有 pre_lock 了，更新状态
        if not any(l.lock_type == LockType.PRE_LOCK for l in self.locks):
            self._update_status()
        
        return expired_jobs


class SlotCreate(BaseModel):
    """Slot 创建请求"""
    node_id: str = Field(..., description="节点 ID")
    worker_id: str = Field(..., description="Worker ID")
    model: str = Field(..., description="模型名称")
    max_concurrency: int = Field(default=1, ge=1)
    input_price: float = Field(..., gt=0)
    output_price: float = Field(..., gt=0)
    avg_latency_ms: int = Field(default=0, ge=0)
    region: Optional[str] = None


class SlotResponse(BaseModel):
    """Slot API 响应"""
    slot_id: str
    node_id: str
    worker_id: str
    model: ModelInfo
    status: SlotStatus
    capacity: CapacityInfo
    pricing: PricingInfo
    performance: PerformanceInfo
    job_sets: JobSet
    locks: List[SlotLock]
    current_job_id: Optional[str] = None
    is_available: bool
