"""
Pre-Lock Service - DCM v3.1
Pre-Lock = 短期资源预占机制

功能:
1. 创建 Pre-Lock 请求
2. 处理 Pre-Lock Ack/Reject
3. TTL 管理和过期处理
4. 转换到 Reserved 状态
"""

from typing import Optional, Dict, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import logging
import time

from ..models.slot import Slot, SlotStatus, SlotLock, LockType

logger = logging.getLogger(__name__)


class PreLockStatus(str, Enum):
    """Pre-Lock 状态"""
    PENDING = "pending"       # 等待 Ack
    LOCKED = "locked"         # 已确认
    REJECTED = "rejected"     # 被拒绝
    EXPIRED = "expired"       # 已过期
    CONVERTED = "converted"   # 已转换为 Reserved


@dataclass
class PreLockRequest:
    """Pre-Lock 请求"""
    job_id: str
    slot_id: str
    ttl_ms: int = 5000
    created_at: int = 0
    
    def __post_init__(self):
        if self.created_at == 0:
            self.created_at = int(time.time() * 1000)
    
    @property
    def expires_at(self) -> int:
        """过期时间戳（毫秒）"""
        return self.created_at + self.ttl_ms
    
    def is_expired(self) -> bool:
        """是否已过期"""
        now_ms = int(time.time() * 1000)
        return now_ms > self.expires_at


@dataclass
class PreLockResult:
    """Pre-Lock 结果"""
    success: bool
    job_id: str
    slot_id: str
    status: PreLockStatus
    expires_at: Optional[int] = None
    reason: Optional[str] = None


class PreLockService:
    """Pre-Lock 服务
    
    生命周期:
    1. PreLockRequest → 发送 Pre-Lock 请求
    2. PreLockAck → 确认锁定
    3. PreLockReject → 拒绝（Slot 满等）
    4. TTL Expiry → 过期释放
    5. Confirm → 转换为 Reserved
    """
    
    def __init__(self, default_ttl_ms: int = 5000):
        """
        Args:
            default_ttl_ms: 默认 TTL（毫秒）
        """
        self.default_ttl_ms = default_ttl_ms
        
        # Pre-Lock 请求表
        self._pending_requests: Dict[str, PreLockRequest] = {}  # job_id → request
        
        # 回调函数
        self._on_lock_confirmed: Optional[Callable] = None
        self._on_lock_expired: Optional[Callable] = None
        self._on_lock_rejected: Optional[Callable] = None
    
    def set_callbacks(
        self,
        on_confirmed: Optional[Callable] = None,
        on_expired: Optional[Callable] = None,
        on_rejected: Optional[Callable] = None,
    ) -> None:
        """设置回调函数
        
        Args:
            on_confirmed: 锁定确认回调 (job_id, slot_id)
            on_expired: 锁定过期回调 (job_id, slot_id)
            on_rejected: 锁定拒绝回调 (job_id, slot_id, reason)
        """
        self._on_lock_confirmed = on_confirmed
        self._on_lock_expired = on_expired
        self._on_lock_rejected = on_rejected
    
    def request_pre_lock(self, job_id: str, slot: Slot, ttl_ms: Optional[int] = None) -> PreLockResult:
        """请求 Pre-Lock
        
        Args:
            job_id: Job ID
            slot: Slot 实例
            ttl_ms: TTL 毫秒（可选）
            
        Returns:
            PreLockResult
        """
        ttl = ttl_ms or self.default_ttl_ms
        
        # 检查 Slot 是否可锁定
        if not slot.is_available():
            return PreLockResult(
                success=False,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.REJECTED,
                reason="slot_not_available",
            )
        
        # 检查容量
        if slot.capacity.available_capacity <= 0:
            return PreLockResult(
                success=False,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.REJECTED,
                reason="capacity_full",
            )
        
        # 尝试创建 Pre-Lock
        if not slot.pre_lock(job_id, ttl):
            return PreLockResult(
                success=False,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.REJECTED,
                reason="pre_lock_failed",
            )
        
        # 记录请求
        request = PreLockRequest(job_id=job_id, slot_id=slot.slot_id, ttl_ms=ttl)
        self._pending_requests[job_id] = request
        
        logger.info(f"Pre-Lock requested: job={job_id}, slot={slot.slot_id}, ttl={ttl}ms")
        
        return PreLockResult(
            success=True,
            job_id=job_id,
            slot_id=slot.slot_id,
            status=PreLockStatus.PENDING,
            expires_at=request.expires_at,
        )
    
    def receive_ack(self, job_id: str, slot: Slot) -> PreLockResult:
        """接收 Pre-Lock Ack
        
        Args:
            job_id: Job ID
            slot: Slot 实例
            
        Returns:
            PreLockResult
        """
        request = self._pending_requests.get(job_id)
        if not request:
            logger.warning(f"Pre-Lock ack received but no pending request: job={job_id}")
            # 仍然尝试确认
            if slot.confirm_pre_lock(job_id):
                return PreLockResult(
                    success=True,
                    job_id=job_id,
                    slot_id=slot.slot_id,
                    status=PreLockStatus.CONVERTED,
                )
            return PreLockResult(
                success=False,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.REJECTED,
                reason="no_pending_request",
            )
        
        # 检查是否过期
        if request.is_expired():
            self._pending_requests.pop(job_id, None)
            slot.release_lock(job_id)
            return PreLockResult(
                success=False,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.EXPIRED,
                reason="pre_lock_expired",
            )
        
        # 确认 Pre-Lock
        if slot.confirm_pre_lock(job_id):
            self._pending_requests.pop(job_id, None)
            
            if self._on_lock_confirmed:
                self._on_lock_confirmed(job_id, slot.slot_id)
            
            logger.info(f"Pre-Lock confirmed: job={job_id}, slot={slot.slot_id}")
            
            return PreLockResult(
                success=True,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.LOCKED,
                expires_at=request.expires_at,
            )
        
        return PreLockResult(
            success=False,
            job_id=job_id,
            slot_id=slot.slot_id,
            status=PreLockStatus.REJECTED,
            reason="confirm_failed",
        )
    
    def receive_reject(self, job_id: str, slot: Slot, reason: str) -> PreLockResult:
        """接收 Pre-Lock Reject
        
        Args:
            job_id: Job ID
            slot: Slot 实例
            reason: 拒绝原因
            
        Returns:
            PreLockResult
        """
        self._pending_requests.pop(job_id, None)
        slot.release_lock(job_id)
        
        if self._on_lock_rejected:
            self._on_lock_rejected(job_id, slot.slot_id, reason)
        
        logger.info(f"Pre-Lock rejected: job={job_id}, slot={slot.slot_id}, reason={reason}")
        
        return PreLockResult(
            success=False,
            job_id=job_id,
            slot_id=slot.slot_id,
            status=PreLockStatus.REJECTED,
            reason=reason,
        )
    
    def check_expired(self, job_id: str, slot: Slot) -> PreLockResult:
        """检查并处理过期
        
        Args:
            job_id: Job ID
            slot: Slot 实例
            
        Returns:
            PreLockResult
        """
        request = self._pending_requests.get(job_id)
        if not request:
            return PreLockResult(
                success=False,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.EXPIRED,
                reason="no_pending_request",
            )
        
        if not request.is_expired():
            return PreLockResult(
                success=True,
                job_id=job_id,
                slot_id=slot.slot_id,
                status=PreLockStatus.PENDING,
                expires_at=request.expires_at,
            )
        
        # 过期处理
        self._pending_requests.pop(job_id, None)
        slot.release_lock(job_id)
        
        if self._on_lock_expired:
            self._on_lock_expired(job_id, slot.slot_id)
        
        logger.info(f"Pre-Lock expired: job={job_id}, slot={slot.slot_id}")
        
        return PreLockResult(
            success=False,
            job_id=job_id,
            slot_id=slot.slot_id,
            status=PreLockStatus.EXPIRED,
            reason="ttl_expired",
        )
    
    def cleanup_slot_expired(self, slot: Slot) -> list[str]:
        """清理 Slot 上所有过期的 Pre-Locks
        
        Args:
            slot: Slot 实例
            
        Returns:
            被清理的 Job IDs
        """
        expired_jobs = slot.cleanup_expired_locks()
        
        for job_id in expired_jobs:
            self._pending_requests.pop(job_id, None)
            if self._on_lock_expired:
                self._on_lock_expired(job_id, slot.slot_id)
        
        return expired_jobs
    
    def get_pending_request(self, job_id: str) -> Optional[PreLockRequest]:
        """获取待处理的 Pre-Lock 请求"""
        return self._pending_requests.get(job_id)
    
    def has_pending(self, job_id: str) -> bool:
        """检查是否有待处理的 Pre-Lock"""
        return job_id in self._pending_requests


# 全局实例
pre_lock_service = PreLockService(default_ttl_ms=5000)
