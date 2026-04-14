"""
Cluster Models - DCM v3.2
Cluster = Node 集合 + Job Queue + 模型服务单元

层级关系:
User → Cluster → Node → Worker → Runtime Adapter
         │
         └── Job Queue (统一入口，分发给 Node/Worker)

核心特性:
1. Cluster 归属于一个 User
2. Cluster 提供一类模型 (qwen, llama...)
3. Cluster 包含多个 Node，每个 Node 有 Worker
4. Cluster 有统一的 Job Queue，抢 Job 后分发给 Node
5. Pre-Lock 短期资源预占机制
6. max_concurrency = 所有 Worker 并发能力之和
"""

from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
import uuid
import time


class ClusterStatus(str, Enum):
    """Cluster 状态 (DCM v3.2)
    
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


class ClusterLock(BaseModel):
    """Cluster Lock 记录"""
    job_id: str = Field(..., description="Job ID")
    lock_type: LockType = Field(..., description="Lock 类型")
    expires_at: Optional[int] = Field(None, description="过期时间戳（毫秒）")
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000))
    tokens: int = Field(default=0, description="占用的 token 数量 (DCM v3.2)")


class ModelInfo(BaseModel):
    """模型信息"""
    family: str = Field(..., description="模型族，如 qwen, llama, gemma")
    name: str = Field(..., description="模型名，如 qwen3-8b")


class CapacityInfo(BaseModel):
    """容量信息 (DCM v3.2)
    
    并发执行规则: active_jobs + reserved_jobs ≤ max_concurrency
    Queue 规则: available_queue >= job_tokens (input + output)
    """
    max_concurrency: int = Field(default=1, ge=1, description="最大并发数")
    active_jobs: int = Field(default=0, ge=0, description="当前活跃 Job 数 (running)")
    reserved_jobs: int = Field(default=0, ge=0, description="已预约 Job 数 (reserved)")
    pre_locked_jobs: int = Field(default=0, ge=0, description="已预锁定 Job 数 (pre_lock)")
    
    # Queue Info (DCM v3.2) / 队列信息 (tokens)
    max_queue: int = Field(default=1500, ge=1, description="最大队列 (tokens)")
    available_queue: int = Field(default=1500, ge=0, description="可用队列 (tokens)")
    
    @property
    def total_jobs(self) -> int:
        """总 Job 数"""
        return self.active_jobs + self.reserved_jobs + self.pre_locked_jobs
    
    @property
    def available_capacity(self) -> int:
        """可用并发容量"""
        return max(0, self.max_concurrency - self.total_jobs)
    
    @property
    def is_full(self) -> bool:
        """是否已满 (并发)"""
        return self.total_jobs >= self.max_concurrency
    
    @property
    def is_idle(self) -> bool:
        """是否空闲 (有可用 token 额度)"""
        return self.available_queue > 0
    
    def reserve_queue(self, tokens: int) -> bool:
        """预留队列容量
        
        Args:
            tokens: 需要的 token 数量 (input + output)
            
        Returns:
            是否成功预留
        """
        if self.available_queue < tokens:
            return False
        self.available_queue -= tokens
        return True
    
    def release_queue(self, tokens: int) -> None:
        """释放队列容量
        
        Args:
            tokens: 释放的 token 数量
        """
        self.available_queue = min(self.max_queue, self.available_queue + tokens)


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


class Cluster(BaseModel):
    """Cluster 模型服务单元 (DCM v3.2)
    
    Cluster 是 DCM v3.2 的核心交易单元:
    - 不关联具体 User（类似 colocation DC）
    - 提供一类模型 (qwen, llama, gemma...)
    - 包含多个 Node，每个 Node 有 Worker
    - Node 关联各自的 User（服务器所有者）
    - 有统一的 Job Queue，抢 Job 后分发给 Node/Worker
    
    层级关系:
    Cluster → Node (user_id) → Worker → Runtime Adapter
      │
      └── 提供同类模型的 Node 聚合
    """
    cluster_id: str = Field(default_factory=lambda: f"cluster_{uuid.uuid4().hex[:8]}")
    
    # 成员 Node 和 Worker (DCM v3.2)
    node_ids: List[str] = Field(default_factory=list, description="所属 Node ID 列表")
    worker_ids: List[str] = Field(default_factory=list, description="所属 Worker ID 列表")
    
    # 兼容字段 (DCM v3.2 之前)
    node_id: Optional[str] = Field(None, description="主 Node ID (兼容)")
    worker_id: Optional[str] = Field(None, description="主 Worker ID (兼容)")
    user_id: Optional[str] = Field(None, description="用户 ID (兼容，可选)")
    
    # 模型与性能
    model: ModelInfo = Field(..., description="模型信息")
    capacity: CapacityInfo = Field(default_factory=CapacityInfo, description="容量信息")
    pricing: PricingInfo = Field(..., description="定价信息")
    performance: PerformanceInfo = Field(default_factory=PerformanceInfo, description="性能信息")
    
    # 状态
    status: ClusterStatus = Field(default=ClusterStatus.FREE, description="Cluster 状态")
    
    # Job Queue (DCM v3.2)
    job_queue: List[str] = Field(default_factory=list, description="Job 队列 (Job IDs)")
    max_queue_size: int = Field(default=100, ge=1, description="最大队列长度")
    
    # Job Sets
    job_sets: JobSet = Field(default_factory=JobSet, description="Job 集合")
    
    # Pre-Lock 管理
    locks: List[ClusterLock] = Field(default_factory=list, description="当前 Locks")
    
    # 兼容性 (保留旧字段)
    current_job_id: Optional[str] = Field(default=None, description="当前 Job ID (兼容)")
    
    # 元数据
    region: Optional[str] = Field(default=None, description="区域")
    created_at: int = Field(default_factory=lambda: 0, description="创建时间戳")
    updated_at: int = Field(default_factory=lambda: 0, description="更新时间戳")
    
    # ==================== 节点管理 ====================
    
    def add_node(self, node_id: str) -> bool:
        """添加 Node
        
        Args:
            node_id: Node ID
            
        Returns:
            是否成功
        """
        if node_id in self.node_ids:
            return False
        self.node_ids.append(node_id)
        self._recalculate_capacity()
        return True
    
    def remove_node(self, node_id: str) -> bool:
        """移除 Node
        
        Args:
            node_id: Node ID
            
        Returns:
            是否成功
        """
        if node_id not in self.node_ids:
            return False
        self.node_ids.remove(node_id)
        self._recalculate_capacity()
        return True
    
    def _recalculate_capacity(self) -> None:
        """重新计算容量 (基于所有 Node 的 Worker 并发能力之和)
        
        TODO: 从 Node/Worker 服务获取实际并发能力
        """
        # 简化: 假设每个 Node 贡献 max_concurrency
        # 实际应从 Worker 服务查询
        total_capacity = len(self.node_ids) * self.capacity.max_concurrency
        self.capacity.max_concurrency = max(1, total_capacity)
    
    # ==================== Job Queue 管理 ====================
    
    def enqueue_job(self, job_id: str) -> bool:
        """Job 入队
        
        Args:
            job_id: Job ID
            
        Returns:
            是否成功
        """
        if len(self.job_queue) >= self.max_queue_size:
            return False
        if job_id in self.job_queue:
            return False
        self.job_queue.append(job_id)
        return True
    
    def dequeue_job(self) -> Optional[str]:
        """Job 出队 (分发给 Node/Worker)
        
        Returns:
            Job ID 或 None
        """
        if not self.job_queue:
            return None
        return self.job_queue.pop(0)
    
    def peek_queue(self) -> List[str]:
        """查看队列 (不取出)
        
        Returns:
            Job ID 列表
        """
        return self.job_queue.copy()
    
    def queue_size(self) -> int:
        """队列大小"""
        return len(self.job_queue)
    
    # ==================== 别名兼容 ====================
    @property
    def slot_id(self) -> str:
        """兼容属性: cluster_id"""
        return self.cluster_id
    
    @slot_id.setter
    def slot_id(self, value: str) -> None:
        """兼容设置: cluster_id"""
        self.cluster_id = value
    
    # ==================== 核心方法 ====================
    
    def is_available(self) -> bool:
        """检查 Cluster 是否可用 (DCM v3.2)
        
        可用条件:
        1. 状态允许 (FREE, PRE_LOCKED, PARTIALLY_RESERVED)
        2. 有可用的 Node（或兼容的 node_id）
        3. 有可用的并发容量
        4. 有可用的队列容量
        """
        if self.status not in [ClusterStatus.FREE, ClusterStatus.PRE_LOCKED, ClusterStatus.PARTIALLY_RESERVED]:
            return False
        
        # 没有 Node 不可用（向后兼容：支持 node_ids 或 node_id）
        if not self.node_ids and not self.node_id:
            return False
        
        # 检查并发容量
        if self.capacity.available_capacity <= 0:
            return False
        
        # 检查队列容量 (DCM v3.2)
        if not self.capacity.is_idle:
            return False
        
        return True
    
    def is_idle(self) -> bool:
        """Cluster 是否空闲 (可用队列 > 0) (DCM v3.2)
        
        空闲表示有可用的 token 额度，可以直接匹配
        """
        return self.capacity.is_idle and self.capacity.available_capacity > 0
    
    def can_accept_job(self) -> bool:
        """是否能接收新 Job
        
        条件: 有并发容量 AND 有队列容量 AND 有可用 Node
        """
        return (
            self.is_available() and
            self.capacity.available_capacity > 0 and
            len(self.job_queue) < self.max_queue_size
        )
    
    def get_pre_lock(self, job_id: str) -> Optional[ClusterLock]:
        """获取 Job 的 Pre-Lock"""
        for lock in self.locks:
            if lock.job_id == job_id and lock.lock_type == LockType.PRE_LOCK:
                return lock
        return None
    
    def pre_lock(self, job_id: str, ttl_ms: int = 5000, tokens: int = 0) -> bool:
        """创建 Pre-Lock
        
        Args:
            job_id: Job ID
            ttl_ms: TTL 毫秒
            tokens: 需要的 token 数量
            
        Returns:
            是否成功
        """
        # 检查容量
        if self.capacity.available_capacity <= 0:
            return False
        
        # 检查队列容量 (DCM v3.2)
        if tokens > 0 and not self.capacity.reserve_queue(tokens):
            return False
        
        # 检查是否已有该 Job 的 lock
        if self.get_pre_lock(job_id):
            if tokens > 0:
                self.capacity.release_queue(tokens)
            return False
        
        now_ms = int(time.time() * 1000)
        lock = ClusterLock(
            job_id=job_id,
            lock_type=LockType.PRE_LOCK,
            expires_at=now_ms + ttl_ms,
            tokens=tokens,
        )
        self.locks.append(lock)
        
        # 更新容量
        self.capacity.pre_locked_jobs += 1
        
        # 状态变为 PRE_LOCKED
        if self.status == ClusterStatus.FREE:
            self.status = ClusterStatus.PRE_LOCKED
        
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
        
        # 保存 tokens 数量用于预约
        tokens = lock.tokens
        
        # 移除 pre_lock
        self.locks = [l for l in self.locks if not (l.job_id == job_id and l.lock_type == LockType.PRE_LOCK)]
        
        # 更新容量: pre_locked -> reserved
        self.capacity.pre_locked_jobs = max(0, self.capacity.pre_locked_jobs - 1)
        
        # 使用统一的 reserve 方法
        return self.reserve(job_id, tokens)
    
    def reserve(self, job_id: str, tokens: int = 0) -> bool:
        """预约 Cluster 给 Job (统一预约方法 - DCM v3.2)
        
        用于 Pre-Lock 确认后或直接匹配时预约 Cluster
        
        Args:
            job_id: Job ID
            tokens: 占用的 token 数量
            
        Returns:
            是否成功
        """
        # 创建 hard_lock
        hard_lock = ClusterLock(
            job_id=job_id,
            lock_type=LockType.HARD_LOCK,
            tokens=tokens,
        )
        self.locks.append(hard_lock)
        
        # 添加到 reserved 列表
        if job_id not in self.job_sets.reserved:
            self.job_sets.reserved.append(job_id)
        
        # 更新容量
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
        
        # 找到要释放的 lock
        lock_to_release = None
        lock_to_use = None
        for lock in self.locks:
            if lock.job_id == job_id:
                lock_to_release = lock.lock_type
                lock_to_use = lock
                break
        
        self.locks = [l for l in self.locks if l.job_id != job_id]
        
        if len(self.locks) == original_len:
            return False
        
        # 根据 lock 类型更新容量
        if lock_to_release == LockType.PRE_LOCK:
            self.capacity.pre_locked_jobs = max(0, self.capacity.pre_locked_jobs - 1)
            # 释放队列容量
            if lock_to_use and lock_to_use.tokens > 0:
                self.capacity.release_queue(lock_to_use.tokens)
        elif lock_to_release == LockType.HARD_LOCK:
            self.capacity.reserved_jobs = max(0, self.capacity.reserved_jobs - 1)
            # 释放队列容量
            if lock_to_use and lock_to_use.tokens > 0:
                self.capacity.release_queue(lock_to_use.tokens)
        elif lock_to_release == LockType.RUNNING:
            self.capacity.active_jobs = max(0, self.capacity.active_jobs - 1)
            # 释放队列容量
            if lock_to_use and lock_to_use.tokens > 0:
                self.capacity.release_queue(lock_to_use.tokens)
        
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
        
        # 获取 hard_lock 的 tokens 数量
        hard_lock_tokens = 0
        for lock in self.locks:
            if lock.job_id == job_id and lock.lock_type == LockType.HARD_LOCK:
                hard_lock_tokens = lock.tokens
                break
        
        # 移动到 running
        self.job_sets.reserved.remove(job_id)
        self.job_sets.running.append(job_id)
        
        # 更新容量
        self.capacity.reserved_jobs = max(0, self.capacity.reserved_jobs - 1)
        self.capacity.active_jobs += 1
        
        # 添加 running lock
        self.locks = [l for l in self.locks if not (l.job_id == job_id and l.lock_type == LockType.HARD_LOCK)]
        running_lock = ClusterLock(
            job_id=job_id,
            lock_type=LockType.RUNNING,
            tokens=hard_lock_tokens,
        )
        self.locks.append(running_lock)
        
        # 预留队列容量 (DCM v3.2)
        self.capacity.reserve_queue(hard_lock_tokens)
        
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
        """根据当前状态更新 Cluster 状态"""
        # 优先检查 RUNNING
        if self.capacity.active_jobs > 0:
            self.status = ClusterStatus.RUNNING
        elif self.capacity.reserved_jobs >= self.capacity.max_concurrency:
            self.status = ClusterStatus.FULLY_RESERVED
        elif self.capacity.reserved_jobs > 0:
            self.status = ClusterStatus.PARTIALLY_RESERVED
        else:
            self.status = ClusterStatus.FREE
    
    def reset_to_free(self) -> None:
        """重置为 FREE"""
        self.status = ClusterStatus.FREE
        self.current_job_id = None
        self.locks = []
        self.job_sets = JobSet()
        self.capacity.reserved_jobs = 0
        self.capacity.active_jobs = 0
    
    def mark_failed(self) -> None:
        """标记为失败"""
        self.status = ClusterStatus.FAILED
        self.current_job_id = None
    
    def cleanup_expired_locks(self) -> List[str]:
        """清理过期的 Pre-Locks (DCM v3.2)
        
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
                    # 释放队列容量 (DCM v3.2)
                    if lock.tokens > 0:
                        self.capacity.release_queue(lock.tokens)
        
        # 如果没有 pre_lock 了，更新状态
        if not any(l.lock_type == LockType.PRE_LOCK for l in self.locks):
            self._update_status()
        
        return expired_jobs
    
    def cleanup_expired_pre_lock(self, job_id: str) -> bool:
        """清理指定 Job 的过期 Pre-Lock (DCM v3.2)
        
        Args:
            job_id: Job ID
            
        Returns:
            是否清理了过期 lock
        """
        for lock in self.locks:
            if lock.job_id == job_id and lock.lock_type == LockType.PRE_LOCK:
                if lock.expires_at:
                    now_ms = int(time.time() * 1000)
                    if now_ms > lock.expires_at:
                        # 清理
                        self.locks.remove(lock)
                        self.capacity.pre_locked_jobs = max(0, self.capacity.pre_locked_jobs - 1)
                        # 释放队列容量 (DCM v3.2)
                        if lock.tokens > 0:
                            self.capacity.release_queue(lock.tokens)
                        self._update_status()
                        return True
        return False


# ==================== Cluster 创建和响应 ====================

class ClusterCreate(BaseModel):
    """Cluster 创建请求"""
    node_id: str = Field(..., description="节点 ID")
    worker_id: str = Field(..., description="Worker ID")
    model: str = Field(..., description="模型名称")
    max_concurrency: int = Field(default=1, ge=1)
    input_price: float = Field(..., gt=0)
    output_price: float = Field(..., gt=0)
    avg_latency_ms: int = Field(default=0, ge=0)
    region: Optional[str] = None


class ClusterResponse(BaseModel):
    """Cluster API 响应"""
    cluster_id: str
    node_id: str
    worker_id: str
    model: ModelInfo
    status: ClusterStatus
    capacity: CapacityInfo
    pricing: PricingInfo
    performance: PerformanceInfo
    job_sets: JobSet
    locks: List[ClusterLock]
    current_job_id: Optional[str] = None
    is_available: bool


# ==================== 别名兼容 ====================
# 保留 Slot 相关别名以便现有代码兼容
Slot = Cluster
SlotStatus = ClusterStatus
SlotLock = ClusterLock


class SlotCreate(BaseModel):
    """Slot 创建请求 (兼容别名)"""
    node_id: str = Field(..., description="节点 ID")
    worker_id: str = Field(..., description="Worker ID")
    model: str = Field(..., description="模型名称")
    max_concurrency: int = Field(default=1, ge=1)
    input_price: float = Field(..., gt=0)
    output_price: float = Field(..., gt=0)
    avg_latency_ms: int = Field(default=0, ge=0)
    region: Optional[str] = None


class SlotResponse(BaseModel):
    """Slot API 响应 (兼容别名)"""
    slot_id: str
    cluster_id: str
    node_id: str
    worker_id: str
    model: ModelInfo
    status: ClusterStatus
    capacity: CapacityInfo
    pricing: PricingInfo
    performance: PerformanceInfo
    job_sets: JobSet
    locks: List[ClusterLock]
    current_job_id: Optional[str] = None
    is_available: bool
