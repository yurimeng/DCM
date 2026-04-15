"""
Job State Manager - 统一管理 Job 状态

问题: API 层同时操作数据库和内存服务，容易导致不一致。

解决方案: 
- 状态变更统一通过 JobStateManager
- Manager 内部处理 DB 和内存状态的同步
- 提供事务保证，失败时回滚

使用方式:
    from src.services.job_state_manager import job_state_manager
    
    # 预锁定 Job
    job_state_manager.prelock_job(job_id, db)
    
    # 确认预锁定
    job_state_manager.prelock_ack(job_id, node_id, db)
    
    # 释放预锁定
    job_state_manager.release_prelock(job_id, db)
    
    # 清理过期预锁定
    job_state_manager.cleanup_expired_prelocks(db)
"""

from typing import Optional, List, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

from sqlalchemy.orm import Session
from ..models import JobStatus, Job
from ..models.db_models import JobDB, JobStatusDB
from ..repositories import JobRepository
from .matching import matching_service
from src.constants import TimeConstants

logger = logging.getLogger(__name__)


class JobStateManager:
    """
    Job 状态管理器
    
    职责:
    1. 统一管理 Job 状态的变更
    2. 确保 DB 和内存状态同步
    3. 提供事务保证
    """
    
    def __init__(self):
        self._memory_sync_enabled = True  # 是否同步内存状态
    
    def _sync_memory_status(self, job_id: str, status: JobStatus, 
                           pre_locked_at: Optional[datetime] = None,
                           pre_lock_expires_at: Optional[datetime] = None) -> None:
        """
        同步内存状态
        
        Args:
            job_id: Job ID
            status: 新状态
            pre_locked_at: 预锁定时间
            pre_lock_expires_at: 预锁定过期时间
        """
        if not self._memory_sync_enabled:
            return
        
        try:
            memory_job = matching_service._pending_jobs.get(job_id)
            if memory_job:
                memory_job.status = status
                memory_job.pre_locked_at = pre_locked_at
                memory_job.pre_lock_expires_at = pre_lock_expires_at
                logger.info(f"[StateSync] Job {job_id} memory status updated to {status.value}")
            else:
                logger.debug(f"[StateSync] Job {job_id} not found in memory, skip")
        except Exception as e:
            logger.warning(f"[StateSync] Failed to sync memory for job {job_id}: {e}")
            # 内存同步失败不影响主流程
    
    def _sync_db_status(self, job_id: str, db: Session, status: JobStatusDB,
                        pre_locked_at: Optional[datetime] = None,
                        pre_lock_expires_at: Optional[datetime] = None) -> Optional[JobDB]:
        """
        同步数据库状态
        
        Returns:
            更新后的 JobDB 或 None
        """
        job_repo = JobRepository(db)
        db_job = job_repo.get(job_id)
        
        if db_job:
            db_job.status = status
            if pre_locked_at is not None:
                db_job.pre_locked_at = pre_locked_at
            if pre_lock_expires_at is not None:
                db_job.pre_lock_expires_at = pre_lock_expires_at
        
        return db_job
    
    def _sync_all(self, job_id: str, db: Session, status: JobStatusDB,
                  status_memory: Optional[JobStatus] = None,
                  pre_locked_at: Optional[datetime] = None,
                  pre_lock_expires_at: Optional[datetime] = None) -> Optional[JobDB]:
        """
        同步所有存储 (DB + Memory)
        
        Args:
            job_id: Job ID
            db: 数据库会话
            status: DB 状态
            status_memory: 内存状态 (如果与 DB 状态不同)
            pre_locked_at: 预锁定时间
            pre_lock_expires_at: 预锁定过期时间
        
        Returns:
            更新后的 JobDB 或 None
        """
        # 1. 更新 DB
        db_job = self._sync_db_status(job_id, db, status, pre_locked_at, pre_lock_expires_at)
        
        # 2. 同步内存 (转换状态枚举)
        if status_memory is None:
            # 自动转换: JobStatusDB -> JobStatus
            status_memory = self._db_status_to_memory(status)
        
        self._sync_memory_status(job_id, status_memory, pre_locked_at, pre_lock_expires_at)
        
        return db_job
    
    def _db_status_to_memory(self, db_status: JobStatusDB) -> JobStatus:
        """转换 DB 状态枚举到内存状态枚举"""
        try:
            # 尝试直接转换 (如果枚举值相同)
            return JobStatus(db_status.value)
        except ValueError:
            # 枚举值不同，手动映射
            mapping = {
                JobStatusDB.CREATED: JobStatus.CREATED,
                JobStatusDB.PENDING: JobStatus.PENDING,
                JobStatusDB.MATCHED: JobStatus.MATCHED,
                JobStatusDB.PRE_LOCKED: JobStatus.PRE_LOCKED,
                JobStatusDB.RESERVED: JobStatus.RESERVED,
                JobStatusDB.DISPATCHED: JobStatus.DISPATCHED,
                JobStatusDB.RUNNING: JobStatus.RUNNING,
                JobStatusDB.COMPLETED: JobStatus.COMPLETED,
                JobStatusDB.FAILED: JobStatus.FAILED,
                JobStatusDB.CANCELLED: JobStatus.CANCELLED,
            }
            return mapping.get(db_status, JobStatus.PENDING)
    
    def prelock_job(self, job_id: str, db: Session) -> Optional[JobDB]:
        """
        预锁定 Job
        
        Args:
            job_id: Job ID
            db: 数据库会话
            
        Returns:
            更新后的 JobDB 或 None
            
        Raises:
            ValueError: Job 不存在或状态不允许预锁定
        """
        job_repo = JobRepository(db)
        db_job = job_repo.get(job_id)
        
        if not db_job:
            raise ValueError(f"Job not found: {job_id}")
        
        if db_job.status != JobStatusDB.MATCHED:
            raise ValueError(f"Cannot prelock job in status: {db_job.status}")
        
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=TimeConstants.PRELOCK_TTL_SECONDS)
        
        # 同步所有存储
        db_job = self._sync_all(
            job_id, db, JobStatusDB.PRE_LOCKED,
            pre_locked_at=now,
            pre_lock_expires_at=expires_at
        )
        
        db.commit()
        
        logger.info(f"[PreLock] Job {job_id} prelocked, expires at {expires_at}")
        
        return db_job
    
    def prelock_ack(self, job_id: str, node_id: str, db: Session) -> Optional[JobDB]:
        """
        确认预锁定 (ACK)
        
        Args:
            job_id: Job ID
            node_id: Node ID
            db: 数据库会话
            
        Returns:
            更新后的 JobDB 或 None
            
        Raises:
            ValueError: Job 不存在或状态不允许 ACK
        """
        job_repo = JobRepository(db)
        db_job = job_repo.get(job_id)
        
        if not db_job:
            raise ValueError(f"Job not found: {job_id}")
        
        if db_job.status != JobStatusDB.PRE_LOCKED:
            raise ValueError(f"Job not in pre_locked status: {db_job.status}")
        
        # 检查是否过期
        if db_job.pre_lock_expires_at and datetime.utcnow() > db_job.pre_lock_expires_at:
            # 已过期，释放 Pre-lock
            self.release_prelock(job_id, db)
            return db_job
        
        # 确认 Pre-lock
        db_job = self._sync_all(
            job_id, db, JobStatusDB.RESERVED,
            pre_locked_at=None,
            pre_lock_expires_at=None
        )
        
        db.commit()
        
        logger.info(f"[PreLock ACK] Job {job_id} confirmed, status: RESERVED")
        
        return db_job
    
    def release_prelock(self, job_id: str, db: Session) -> Optional[JobDB]:
        """
        释放预锁定
        
        Args:
            job_id: Job ID
            db: 数据库会话
            
        Returns:
            更新后的 JobDB 或 None
            
        Raises:
            ValueError: Job 不存在或状态不允许释放
        """
        job_repo = JobRepository(db)
        db_job = job_repo.get(job_id)
        
        if not db_job:
            raise ValueError(f"Job not found: {job_id}")
        
        if db_job.status != JobStatusDB.PRE_LOCKED:
            raise ValueError(f"Job not in pre_locked status: {db_job.status}")
        
        # 释放 Pre-lock
        db_job = self._sync_all(
            job_id, db, JobStatusDB.MATCHED,
            pre_locked_at=None,
            pre_lock_expires_at=None
        )
        
        db.commit()
        
        logger.info(f"[PreLock Release] Job {job_id} released, status: MATCHED")
        
        return db_job
    
    def cleanup_expired_prelocks(self, db: Session) -> int:
        """
        清理所有过期的预锁定
        
        Args:
            db: 数据库会话
            
        Returns:
            清理的 Job 数量
        """
        # 查找所有过期的 Pre-lock
        expired_jobs = db.query(JobDB).filter(
            JobDB.status == JobStatusDB.PRE_LOCKED,
            JobDB.pre_lock_expires_at < datetime.utcnow()
        ).all()
        
        released_count = 0
        for job in expired_jobs:
            try:
                self._sync_all(
                    job.job_id, db, JobStatusDB.MATCHED,
                    pre_locked_at=None,
                    pre_lock_expires_at=None
                )
                released_count += 1
            except Exception as e:
                logger.warning(f"[Cleanup] Failed to release job {job.job_id}: {e}")
        
        db.commit()
        
        logger.info(f"[Cleanup] Released {released_count} expired pre-locks")
        
        return released_count
    
    def update_job_status(self, job_id: str, db: Session, 
                          status: JobStatusDB,
                          memory_status: Optional[JobStatus] = None,
                          **kwargs) -> Optional[JobDB]:
        """
        通用状态更新
        
        Args:
            job_id: Job ID
            db: 数据库会话
            status: DB 状态
            memory_status: 内存状态 (可选，默认自动转换)
            **kwargs: 其他字段 (如 completed_at, result 等)
            
        Returns:
            更新后的 JobDB 或 None
        """
        job_repo = JobRepository(db)
        db_job = job_repo.get(job_id)
        
        if not db_job:
            raise ValueError(f"Job not found: {job_id}")
        
        # 更新字段
        db_job.status = status
        for key, value in kwargs.items():
            if hasattr(db_job, key):
                setattr(db_job, key, value)
        
        # 同步内存
        if memory_status is None:
            memory_status = self._db_status_to_memory(status)
        self._sync_memory_status(job_id, memory_status)
        
        db.commit()
        
        return db_job


# ============================================================================
# 全局单例
# ============================================================================

job_state_manager = JobStateManager()


# ============================================================================
# 便捷函数
# ============================================================================

def prelock_job(job_id: str, db: Session) -> Optional[JobDB]:
    """预锁定 Job"""
    return job_state_manager.prelock_job(job_id, db)


def prelock_ack(job_id: str, node_id: str, db: Session) -> Optional[JobDB]:
    """确认预锁定"""
    return job_state_manager.prelock_ack(job_id, node_id, db)


def release_prelock(job_id: str, db: Session) -> Optional[JobDB]:
    """释放预锁定"""
    return job_state_manager.release_prelock(job_id, db)


def cleanup_expired_prelocks(db: Session) -> int:
    """清理过期预锁定"""
    return job_state_manager.cleanup_expired_prelocks(db)
