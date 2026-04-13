"""
Match Engine 2.0 - DCM v3.1
整合 F3.1-F3.7 所有组件 + Pre-Lock 机制

Match 流程 (DCM v3.1):
1. Job/Slot 注册到 Order Book
2. 触发匹配:
   a. 获取候选 Slots
   b. Hard Filter 过滤
   c. Scoring 评分排序
   d. Pre-Lock 请求
   e. Pre-Lock Ack 确认
   f. 创建 Match
3. Dispatch: 分发到 Worker
4. 执行完成: Release Slot
"""

from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from ..models import (
    Slot, SlotStatus, ModelInfo, CapacityInfo, PricingInfo, PerformanceInfo,
    Job, JobStatus, Match, Node
)
from .order_book import OrderBook
from .hard_filter import HardFilter, create_default_filter
from .compatibility import CompatibilityMatrix, compatibility_matrix
from .scoring import ScoringFunction, scoring_function
from .pre_lock import PreLockService, PreLockResult, PreLockStatus, pre_lock_service

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果 (DCM v3.1)"""
    success: bool
    pre_locked: bool = False           # 是否已 Pre-Lock
    slot: Optional[Slot] = None        # 匹配的 Slot
    job: Optional[Job] = None           # Job 对象
    score: Optional[float] = None      # 匹配评分
    pre_lock_expires_at: Optional[int] = None  # Pre-Lock 过期时间
    reason: Optional[str] = None        # 失败原因


@dataclass
class DispatchResult:
    """分发结果 (DCM v3.1)"""
    success: bool
    job_id: str
    slot_id: Optional[str] = None
    worker_id: Optional[str] = None
    reason: Optional[str] = None


class MatchEngineV2:
    """
    Match Engine 2.0 - DCM v3.1 Slot-based 撮合引擎
    
    核心功能:
    1. Job/Slot 管理
    2. 匹配算法 (Hard Filter + Scoring)
    3. Pre-Lock 机制
    4. Multi-Job 并发支持
    """
    
    def __init__(
        self,
        order_book: Optional[OrderBook] = None,
        hard_filter: Optional[HardFilter] = None,
        compatibility: Optional[CompatibilityMatrix] = None,
        scoring: Optional[ScoringFunction] = None,
        pre_lock_service: Optional[PreLockService] = None,
    ):
        self.order_book = order_book or OrderBook()
        self.hard_filter = hard_filter or create_default_filter()
        self.compatibility = compatibility or compatibility_matrix
        self.scoring = scoring or scoring_function
        
        # Pre-Lock 服务（使用传入的或创建新的）
        self.pre_lock = pre_lock_service if pre_lock_service else PreLockService()
        
        # 内部状态
        self._slots: Dict[str, Slot] = {}
        self._matches: Dict[str, Match] = {}
        self._job_to_match: Dict[str, str] = {}  # job_id → match_id
        self._slot_jobs: Dict[str, str] = {}      # slot_id → job_id
        self._job_slot: Dict[str, str] = {}       # job_id → slot_id
        
        # Pre-Lock 回调设置
        self.pre_lock.set_callbacks(
            on_confirmed=self._on_pre_lock_confirmed,
            on_expired=self._on_pre_lock_expired,
            on_rejected=self._on_pre_lock_rejected,
        )
    
    # ===== Slot 管理 =====
    
    def register_slot(self, slot: Slot) -> None:
        """注册 Slot"""
        self._slots[slot.slot_id] = slot
        self.order_book.add_slot(slot)
        logger.info(f"Slot registered: {slot.slot_id} ({slot.model.name})")
    
    def unregister_slot(self, slot_id: str) -> Optional[Slot]:
        """注销 Slot"""
        slot = self._slots.pop(slot_id, None)
        if slot:
            self.order_book.remove_slot(slot_id)
            logger.info(f"Slot unregistered: {slot_id}")
        return slot
    
    def get_slot(self, slot_id: str) -> Optional[Slot]:
        """获取 Slot"""
        return self._slots.get(slot_id)
    
    # ===== Job 管理 =====
    
    def submit_job(self, job: Job) -> None:
        """提交 Job"""
        self.order_book.add_job(job)
        logger.info(f"Job submitted: {job.job_id} (model: {job.model_requirement})")
    
    def cancel_job(self, job_id: str) -> Optional[Job]:
        """取消 Job（支持已匹配的 Job）"""
        job = self.order_book.remove_job(job_id)
        
        # 如果不在 order book，尝试从 _job_slot 查找
        if not job:
            slot_id = self._job_slot.get(job_id)
            if slot_id:
                slot = self.get_slot(slot_id)
                if slot:
                    # 释放锁
                    slot.release_lock(job_id)
                self._job_slot.pop(job_id, None)
                logger.info(f"Job cancelled (matched): {job_id}")
                # 返回一个标记对象
                class CancelledJob:
                    job_id: str
                    status: str = "cancelled"
                return CancelledJob()
        else:
            # 释放相关锁
            slot_id = self._job_slot.get(job_id)
            if slot_id:
                slot = self.get_slot(slot_id)
                if slot:
                    slot.release_lock(job_id)
                self._job_slot.pop(job_id, None)
            logger.info(f"Job cancelled: {job_id}")
        
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """获取 Job"""
        for job in self.order_book.get_all_jobs():
            if job.job_id == job_id:
                return job
        return None
    
    # ===== 匹配核心 (DCM v3.1 with Pre-Lock) =====
    
    def match_job(self, job_id: str, pre_lock_ttl_ms: int = 5000) -> MatchResult:
        """
        为 Job 匹配最优 Slot (Pre-Lock 模式)
        
        Args:
            job_id: Job ID
            pre_lock_ttl_ms: Pre-Lock TTL (毫秒)
            
        Returns:
            MatchResult
        """
        job = self.get_job(job_id)
        if not job:
            return MatchResult(success=False, reason="job_not_found")
        
        # 获取候选 Slots
        family = None
        if job.model_requirement:
            import re
            base = job.model_requirement.split(":")[0]
            match = re.match(r'^([a-zA-Z]+)', base)
            family = match.group(1).lower() if match else base.lower()
        
        candidate_slots = self.order_book.get_slots(family)
        if not candidate_slots:
            if not job.model_requirement:
                candidate_slots = self.order_book.get_slots()
        
        if not candidate_slots:
            return MatchResult(success=False, reason="no_available_slots")
        
        # Hard Filter（会过滤掉不兼容的模型）
        filtered_slots = self.hard_filter.filter_many(candidate_slots, job)
        if not filtered_slots:
            return MatchResult(success=False, reason="no_slots_passed_filter")
        
        # Scoring 排序
        ranked = self.scoring.rank_slots(filtered_slots, job)
        
        # 尝试 Pre-Lock 最优 Slot
        for best_slot, best_score in ranked:
            # 清理该 Slot 上过期的 Pre-Locks
            self.pre_lock.cleanup_slot_expired(best_slot)
            
            # 请求 Pre-Lock
            pre_lock_result = self.pre_lock.request_pre_lock(
                job_id, best_slot, pre_lock_ttl_ms
            )
            
            if pre_lock_result.success:
                # Pre-Lock 成功，立即 Ack 确认
                ack_result = self.pre_lock.receive_ack(job_id, best_slot)
                
                if ack_result.success:
                    # 更新 Job 状态
                    job.status = JobStatus.MATCHED
                    job.matched_at = datetime.utcnow()
                    job.slot_id = best_slot.slot_id
                    job.node_id = best_slot.node_id
                    job.worker_id = best_slot.worker_id
                    
                    # 创建 Match
                    match = Match(
                        job_id=job.job_id,
                        slot_id=best_slot.slot_id,
                        node_id=best_slot.node_id,
                        worker_id=best_slot.worker_id,
                        locked_price=job.bid_price,
                        model=best_slot.model.name,
                    )
                    self._matches[match.match_id] = match
                    self._job_to_match[job.job_id] = match.match_id
                    self._job_slot[job.job_id] = best_slot.slot_id
                    
                    # 从 Order Book 移除 Job
                    self.order_book.remove_job(job.job_id)
                    
                    logger.info(f"Match created: {match.match_id} (job={job.job_id}, slot={best_slot.slot_id}, score={best_score:.3f})")
                    
                    return MatchResult(
                        success=True,
                        pre_locked=True,
                        slot=best_slot,
                        job=job,
                        score=best_score,
                        pre_lock_expires_at=pre_lock_result.expires_at,
                    )
                else:
                    # Ack 失败，释放锁
                    best_slot.release_lock(job_id)
            
            # 当前 Slot Pre-Lock 失败，尝试下一个
            logger.debug(f"Pre-Lock failed for slot {best_slot.slot_id}, trying next")
        
        return MatchResult(success=False, reason="all_slots_pre_lock_failed")
    
    def match_job_simple(self, job_id: str) -> MatchResult:
        """
        简化的匹配（无 Pre-Lock，用于向后兼容）
        """
        job = self.get_job(job_id)
        if not job:
            return MatchResult(success=False, reason="job_not_found")
        
        family = None
        if job.model_requirement:
            import re
            base = job.model_requirement.split(":")[0]
            match = re.match(r'^([a-zA-Z]+)', base)
            family = match.group(1).lower() if match else base.lower()
        
        candidate_slots = self.order_book.get_slots(family)
        if not candidate_slots:
            if not job.model_requirement:
                candidate_slots = self.order_book.get_slots()
        
        if not candidate_slots:
            return MatchResult(success=False, reason="no_available_slots")
        
        filtered_slots = self.hard_filter.filter_many(candidate_slots, job)
        if not filtered_slots:
            return MatchResult(success=False, reason="no_slots_passed_filter")
        
        ranked = self.scoring.rank_slots(filtered_slots, job)
        best_slot, best_score = ranked[0]
        
        # 直接预约
        if best_slot.reserve(job.job_id):
            if not best_slot.is_available():
                self.order_book.remove_slot(best_slot.slot_id)
            
            match = Match(
                job_id=job.job_id,
                slot_id=best_slot.slot_id,
                node_id=best_slot.node_id,
                worker_id=best_slot.worker_id,
                locked_price=job.bid_price,
                model=best_slot.model.name,
            )
            
            self._matches[match.match_id] = match
            self._job_to_match[job.job_id] = match.match_id
            self._slot_jobs[best_slot.slot_id] = job.job_id
            
            self.order_book.remove_job(job.job_id)
            
            job.status = JobStatus.MATCHED
            job.matched_at = datetime.utcnow()
            job.slot_id = best_slot.slot_id
            
            logger.info(f"Match created: {match.match_id} (job={job.job_id}, slot={best_slot.slot_id}, score={best_score:.3f})")
            
            return MatchResult(
                success=True,
                slot=best_slot,
                job=job,
                score=best_score,
            )
        
        return MatchResult(success=False, reason="reserve_failed")
    
    # ===== Dispatch (DCM v3.1) =====
    
    def dispatch_job(self, job_id: str) -> DispatchResult:
        """
        分发 Job 到 Worker 执行
        
        Args:
            job_id: Job ID
            
        Returns:
            DispatchResult
        """
        # 先检查是否已分配 slot
        slot_id = self._job_slot.get(job_id)
        if not slot_id:
            return DispatchResult(success=False, job_id=job_id, reason="no_slot_assigned")
        
        slot = self.get_slot(slot_id)
        if not slot:
            return DispatchResult(success=False, job_id=job_id, slot_id=slot_id, reason="slot_not_found")
        
        # 检查 Job 是否在 reserved 列表
        if job_id not in slot.job_sets.reserved:
            return DispatchResult(success=False, job_id=job_id, slot_id=slot_id, reason="job_not_reserved")
        
        # 尝试获取 Job（可能在 order book 中）
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.DISPATCHED
            job.dispatched_at = datetime.utcnow()
        
        logger.info(f"Job dispatched: {job_id} -> slot={slot_id}, worker={slot.worker_id}")
        
        return DispatchResult(
            success=True,
            job_id=job_id,
            slot_id=slot_id,
            worker_id=slot.worker_id,
        )
    
    def start_job_execution(self, job_id: str) -> bool:
        """
        开始执行 Job
        
        Args:
            job_id: Job ID
            
        Returns:
            是否成功
        """
        slot_id = self._job_slot.get(job_id)
        if not slot_id:
            return False
        
        slot = self.get_slot(slot_id)
        if not slot:
            return False
        
        # 更新 Job 状态
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.RUNNING
        
        return slot.start_running(job_id)
    
    # ===== Job 完成 =====
    
    def complete_job(self, job_id: str, result: Optional[str] = None) -> bool:
        """
        完成 Job
        
        Args:
            job_id: Job ID
            result: 执行结果 (可选)
            
        Returns:
            是否成功
        """
        slot_id = self._job_slot.get(job_id)
        if not slot_id:
            return False
        
        slot = self.get_slot(slot_id)
        if not slot:
            return False
        
        # 释放锁
        if not slot.finish_job(job_id):
            return False
        
        # 更新 Job 状态
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            if result:
                job.result = result
        
        # 清理映射
        self._slot_jobs.pop(slot_id, None)
        self._job_slot.pop(job_id, None)
        
        logger.info(f"Job completed on slot {slot_id}")
        
        return True
    
    def fail_job(self, job_id: str, reason: str) -> bool:
        """
        标记 Job 失败
        
        Args:
            job_id: Job ID
            reason: 失败原因
            
        Returns:
            是否成功
        """
        slot_id = self._job_slot.get(job_id)
        if not slot_id:
            return False
        
        slot = self.get_slot(slot_id)
        if not slot:
            return False
        
        # 释放锁
        slot.release_lock(job_id)
        
        # 更新 Job 状态
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.FAILED
            job.retry_count += 1
        
        # 清理映射
        self._slot_jobs.pop(slot_id, None)
        self._job_slot.pop(job_id, None)
        
        logger.warning(f"Job failed: {job_id}, reason={reason}")
        
        return True
    
    # ===== Pre-Lock 回调 =====
    
    def _on_pre_lock_confirmed(self, job_id: str, slot_id: str) -> None:
        """Pre-Lock 确认回调"""
        logger.info(f"Pre-Lock confirmed: job={job_id}, slot={slot_id}")
    
    def _on_pre_lock_expired(self, job_id: str, slot_id: str) -> None:
        """Pre-Lock 过期回调"""
        logger.warning(f"Pre-Lock expired: job={job_id}, slot={slot_id}")
        # 触发重新匹配
        self._job_slot.pop(job_id, None)
    
    def _on_pre_lock_rejected(self, job_id: str, slot_id: str, reason: str) -> None:
        """Pre-Lock 拒绝回调"""
        logger.warning(f"Pre-Lock rejected: job={job_id}, slot={slot_id}, reason={reason}")
        self._job_slot.pop(job_id, None)
    
    # ===== Slot Pool 操作 =====
    
    def poll_slot(self, slot_id: str) -> Optional[Job]:
        """Slot 主动拉取 Job
        
        Args:
            slot_id: Slot ID
            
        Returns:
            Job 或 None
        """
        slot = self.get_slot(slot_id)
        if not slot:
            logger.warning(f"Slot not found: {slot_id}")
            return None
        
        if slot.status not in [SlotStatus.FREE, SlotStatus.PARTIALLY_RESERVED]:
            logger.debug(f"Slot {slot_id} not free (status: {slot.status})")
            return None
        
        # 检查容量
        if not slot.is_available():
            return None
        
        # 从 Order Book 获取候选 Jobs
        candidate_jobs = self.order_book.get_all_jobs()
        if not candidate_jobs:
            return None
        
        # 按优先级和创建时间排序
        candidate_jobs.sort(key=lambda j: (-j.priority, j.created_at))
        
        # 尝试匹配
        for job in candidate_jobs:
            # Hard Filter
            passed, _ = self.hard_filter.filter(slot, job)
            if not passed:
                continue
            
            # 尝试 Pre-Lock
            pre_lock_result = self.pre_lock.request_pre_lock(job.job_id, slot)
            if pre_lock_result.success:
                ack_result = self.pre_lock.receive_ack(job.job_id, slot)
                if ack_result.success:
                    # 更新 Job
                    job.slot_id = slot.slot_id
                    job.node_id = slot.node_id
                    job.worker_id = slot.worker_id
                    job.status = JobStatus.MATCHED
                    
                    # 从 Order Book 移除
                    self.order_book.remove_job(job.job_id)
                    self._job_slot[job.job_id] = slot.slot_id
                    
                    logger.info(f"Slot {slot_id} polled job: {best_job.job_id} (score: {best_score:.3f})")
                    return job
        
        return None
    
    def release_slot(self, slot_id: str) -> bool:
        """释放 Slot (slot 主动释放资源)
        
        Args:
            slot_id: Slot ID
            
        Returns:
            是否成功
        """
        slot = self.get_slot(slot_id)
        if not slot:
            return False
        
        job_id = self._slot_jobs.get(slot_id)
        
        if job_id:
            slot.release_lock(job_id)
            job = self.get_job(job_id)
            if job:
                job.status = JobStatus.RELEASED
        
        logger.info(f"Slot {slot_id} reset to FREE")
        
        return True
    
    def reset_slot(self, slot_id: str) -> bool:
        """重置 Slot 到初始状态"""
        slot = self.get_slot(slot_id)
        if not slot:
            return False
        
        slot.reset_to_free()
        
        # 清理所有关联的 Job 映射
        for job_id in list(self._job_slot.keys()):
            if self._job_slot[job_id] == slot_id:
                self._job_slot.pop(job_id)
        
        self._slot_jobs.pop(slot_id, None)
        
        return True
    
    # ===== 统计 =====
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        total_slots = len(self._slots)
        available_slots = sum(1 for s in self._slots.values() if s.is_available())
        pending_jobs = len(self.order_book.get_all_jobs())
        
        return {
            "total_slots": total_slots,
            "available_slots": available_slots,
            "pending_jobs": pending_jobs,
            "active_matches": len(self._matches),
            "slot_utilization": (total_slots - available_slots) / max(1, total_slots),
        }
