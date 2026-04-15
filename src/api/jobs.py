"""
Jobs API - F1: Job 提交与管理系统
来源: Function/F1
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List

from ..database import get_db
from ..models import Job, JobCreate, JobResponse, JobStatus, JobDB
from ..models.db_models import JobStatusDB, EscrowDB, EscrowStatusDB
from ..repositories import JobRepository, EscrowRepository
from ..services import matching_service, escrow_service
from config import settings

router = APIRouter(prefix="/jobs", tags=["jobs"])

import logging
logger = logging.getLogger(__name__)


class PreLockACKRequest(BaseModel):
    """Pre-lock ACK 请求"""
    node_id: str


@router.get("/ping")
async def ping():
    """简单的 ping 测试"""
    return {"pong": True, "router": "jobs"}


def _safe_status(status) -> str:
    """安全获取状态值"""
    if hasattr(status, 'value'):
        return status.value
    return str(status)


@router.post("", response_model=JobResponse)
async def create_job(
    job_create: JobCreate,
    db: Session = Depends(get_db)
):
    """
    提交新的 Job
    
    自动执行:
    1. 创建 Job 记录
    2. Escrow 锁定
    3. 触发撮合引擎
    """
    try:
        # 1. 创建 Job Pydantic 模型
        job = Job(**job_create.model_dump())
        
        # 2. 保存到数据库
        job_repo = JobRepository(db)
        db_job = job_repo.create(job)
        
        # 3. 创建 Escrow（数据库）
        db_escrow = EscrowDB(
            escrow_id=f"escrow_{job.job_id}",
            job_id=job.job_id,
            locked_amount=escrow_service._calculate_escrow(
                job.bid_price,
                job.input_tokens,
                job.output_tokens_limit
            ),
            status=EscrowStatusDB.LOCKED,
        )
        db.add(db_escrow)
        db.commit()
        
        # 4. 触发撮合（同步到内存服务）
        matching_service.add_job(job)
        logger.info(f"[MATCH DEBUG] Job {job.job_id} added to matching service")
        match = matching_service.trigger_match(job.job_id)
        logger.info(f"[MATCH DEBUG] trigger_match result: {match}")
        
        if match:
            # 更新 Job 状态（不自动 commit）
            db_job = job_repo.get(job.job_id)
            if db_job:
                from datetime import datetime
                db_job.status = JobStatusDB.MATCHED
                db_job.matched_at = datetime.utcnow()
            
            # 保存 Match 到数据库
            from ..models.db_models import MatchDB
            db_match = MatchDB(
                match_id=match.match_id,
                job_id=match.job_id,
                node_id=match.node_id,
                locked_price=match.locked_price,
                matched_at=match.matched_at,
            )
            db.add(db_match)
            
            # 更新 Escrow
            db_escrow.match_id = match.match_id
            
            # 一次性提交所有更改
            db.commit()
        
        # 5. 返回响应
        return JobResponse(
            job_id=job.job_id,
            escrow_amount=db_escrow.locked_amount,
            status=JobStatus(_safe_status(db_job.status)),
            created_at=db_job.created_at,
            matched_at=db_job.matched_at,
        )
    except Exception as e:
        logger.error(f"Job creation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/debug/db-status")
async def debug_db_status(db: Session = Depends(get_db)):
    """调试端点: 检查数据库状态"""
    from ..models.db_models import JobDB, EscrowDB, MatchDB, NodeDB
    
    return {
        "jobs": db.query(JobDB).count(),
        "escrows": db.query(EscrowDB).count(),
        "matches": db.query(MatchDB).count(),
        "nodes": db.query(NodeDB).count(),
    }


@router.get("/debug/matching-status")
async def debug_matching_status(db: Session = Depends(get_db)):
    """
    调试端点：检查匹配系统状态
    """
    from ..services.node_status_store import (
        list_online_nodes, list_nodes, node_status_store
    )
    from ..repositories import NodeRepository, JobRepository
    from ..models.db_models import JobDB
    
    # DB nodes
    node_repo = NodeRepository(db)
    all_db_nodes = node_repo.list_all()
    
    # NodeStatusStore nodes
    all_store_nodes = list_nodes()
    online_store_nodes = list_online_nodes()
    
    # Pending jobs
    pending_jobs = db.query(JobDB).filter(JobDB.status == "pending").all()
    
    return {
        "db_nodes": {
            "total": len(all_db_nodes),
            "nodes": [
                {
                    "node_id": n.node_id[:20],
                    "status": n.status.value,
                    "ask_price": n.ask_price,
                    "model_support": n.model_support,
                }
                for n in all_db_nodes
            ]
        },
        "node_status_store": {
            "total_nodes": len(all_store_nodes),
            "online_nodes": len(online_store_nodes),
            "online_node_ids": [n.node_id[:20] for n in online_store_nodes],
            "all_node_ids": [n.node_id[:20] for n in all_store_nodes],
        },
        "pending_jobs": {
            "total": len(pending_jobs),
            "jobs": [
                {
                    "job_id": j.job_id[:20],
                    "model": j.model,
                    "bid_price": float(j.bid_price),
                }
                for j in pending_jobs
            ]
        },
        "backend_type": type(node_status_store._backend).__name__,
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    db: Session = Depends(get_db)
):
    """查询 Job 详情"""
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 获取 Escrow
    escrow_repo = EscrowRepository(db)
    db_escrow = escrow_repo.get_by_job(job_id)
    
    return {
        "job_id": db_job.job_id,
        "model": db_job.model,
        "input_tokens": db_job.input_tokens,
        "output_tokens_limit": db_job.output_tokens_limit,
        "max_latency": db_job.max_latency,
        "bid_price": db_job.bid_price,
        "status": _safe_status(db_job.status),
        "created_at": db_job.created_at.isoformat() if db_job.created_at else None,
        "matched_at": db_job.matched_at.isoformat() if db_job.matched_at else None,
        "completed_at": db_job.completed_at.isoformat() if db_job.completed_at else None,
        "actual_output_tokens": db_job.actual_output_tokens,
        "result": db_job.result,
        "final_price": db_job.final_price,
        "retry_count": db_job.retry_count,
        "escrow": {
            "escrow_id": db_escrow.escrow_id if db_escrow else None,
            "locked_amount": db_escrow.locked_amount if db_escrow else None,
            "spent_amount": db_escrow.spent_amount if db_escrow else None,
            "refund_amount": db_escrow.refund_amount if db_escrow else None,
            "status": _safe_status(db_escrow.status) if db_escrow else None,
            "completed_at": db_escrow.completed_at.isoformat() if db_escrow and db_escrow.completed_at else None,
            "auto_complete_at": db_escrow.auto_complete_at.isoformat() if db_escrow and db_escrow.auto_complete_at else None,
            "settled_at": db_escrow.settled_at.isoformat() if db_escrow and db_escrow.settled_at else None,
            "cancelled_at": db_escrow.cancelled_at.isoformat() if db_escrow and db_escrow.cancelled_at else None,
            "cancelled_by": db_escrow.cancelled_by if db_escrow else None,
            "cancel_reason": db_escrow.cancel_reason if db_escrow else None,
        } if db_escrow else None,
        "match_id": matching_service._job_to_match.get(job_id) if job_id in matching_service._job_to_match else None,
    }


@router.get("/{job_id}/escrow")
async def get_job_escrow(
    job_id: str,
    db: Session = Depends(get_db)
):
    """查询 Job 的 Escrow 状态"""
    escrow_repo = EscrowRepository(db)
    db_escrow = escrow_repo.get_by_job(job_id)
    
    if not db_escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    
    return {
        "job_id": db_escrow.job_id,
        "escrow_id": db_escrow.escrow_id,
        "match_id": db_escrow.match_id,
        "locked_amount": db_escrow.locked_amount,
        "spent_amount": db_escrow.spent_amount,
        "refund_amount": db_escrow.refund_amount,
        "status": _safe_status(db_escrow.status),
        "created_at": db_escrow.created_at.isoformat() if db_escrow.created_at else None,
        "completed_at": db_escrow.completed_at.isoformat() if db_escrow.completed_at else None,
        "auto_complete_at": db_escrow.auto_complete_at.isoformat() if db_escrow.auto_complete_at else None,
        "settled_at": db_escrow.settled_at.isoformat() if db_escrow.settled_at else None,
        "refunded_at": db_escrow.refunded_at.isoformat() if db_escrow.refunded_at else None,
        "cancelled_at": db_escrow.cancelled_at.isoformat() if db_escrow.cancelled_at else None,
        "cancelled_by": db_escrow.cancelled_by,
        "cancel_reason": db_escrow.cancel_reason,
        "actual_tokens": db_escrow.actual_tokens,
        "actual_cost": db_escrow.actual_cost,
        "platform_fee": db_escrow.platform_fee,
        "node_earn": db_escrow.node_earn,
        "refund_reason": db_escrow.refund_reason,
    }


@router.post("/{job_id}/escrow/cancel")
async def cancel_job_escrow(
    job_id: str,
    cancel_data: dict,
    db: Session = Depends(get_db)
):
    """
    取消 Job 的 Escrow（全额退款）
    
    只能在 COMPLETED 之前取消（LOCKED 或 COMPLETED 状态）
    """
    from datetime import datetime
    from ..models.db_models import EscrowDB, EscrowStatusDB
    from ..services.settlement_config import settlement_config
    
    reason = cancel_data.get("reason", "User cancelled")
    cancelled_by = cancel_data.get("cancelled_by", "user")
    
    # 验证 Job 存在
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 检查 Escrow 是否存在
    escrow_repo = EscrowRepository(db)
    db_escrow = escrow_repo.get_by_job(job_id)
    if not db_escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    
    # 检查是否允许取消
    if not settlement_config.escrow_allow_cancellation:
        raise HTTPException(status_code=400, detail="Escrow cancellation is not allowed")
    
    # 检查状态
    if db_escrow.status not in [EscrowStatusDB.LOCKED, EscrowStatusDB.COMPLETED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel: escrow status is {db_escrow.status.value}"
        )
    
    # 执行取消
    db_escrow.status = EscrowStatusDB.CANCELLED
    db_escrow.refund_amount = db_escrow.locked_amount
    db_escrow.cancelled_at = datetime.utcnow()
    db_escrow.cancelled_by = cancelled_by
    db_escrow.cancel_reason = reason
    db.commit()
    db.refresh(db_escrow)
    
    return {
        "success": True,
        "job_id": job_id,
        "status": "cancelled",
        "refund_amount": db_escrow.refund_amount,
        "cancelled_at": db_escrow.cancelled_at.isoformat() if db_escrow.cancelled_at else None,
        "cancel_reason": reason,
    }


@router.post("/{job_id}/escrow/settle")
async def settle_job_escrow(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    手动结算 Job 的 Escrow（跳过延迟等待）
    """
    from datetime import datetime
    from ..models.db_models import EscrowDB, EscrowStatusDB
    from ..services.settlement_config import settlement_config
    from config import settings
    
    # 验证 Job 存在
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 检查 Escrow 是否存在
    escrow_repo = EscrowRepository(db)
    db_escrow = escrow_repo.get_by_job(job_id)
    if not db_escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    
    # 检查状态
    if db_escrow.status not in [EscrowStatusDB.LOCKED, EscrowStatusDB.COMPLETED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot settle: escrow status is {db_escrow.status.value}"
        )
    
    # 计算结算金额
    actual_tokens = db_job.actual_output_tokens or 0
    actual_cost = round(db_escrow.locked_amount * actual_tokens / (db_job.input_tokens + db_job.output_tokens_limit), 8) if (db_job.input_tokens + db_job.output_tokens_limit) > 0 else db_escrow.locked_amount
    
    # 结算分配
    platform_fee = actual_cost * settlement_config.platform_fee_rate
    node_earn = actual_cost * settlement_config.node_earn_rate
    refund_amount = db_escrow.locked_amount - actual_cost
    
    # 更新 Escrow
    db_escrow.status = EscrowStatusDB.SETTLED
    db_escrow.settled_at = datetime.utcnow()
    db_escrow.spent_amount = actual_cost
    db_escrow.refund_amount = max(0, refund_amount)
    db_escrow.actual_tokens = actual_tokens
    db_escrow.actual_cost = actual_cost
    db_escrow.platform_fee = platform_fee
    db_escrow.node_earn = node_earn
    db.commit()
    db.refresh(db_escrow)
    
    return {
        "success": True,
        "job_id": job_id,
        "status": "settled",
        "spent_amount": db_escrow.spent_amount,
        "refund_amount": db_escrow.refund_amount,
        "platform_fee": db_escrow.platform_fee,
        "node_earn": db_escrow.node_earn,
        "settled_at": db_escrow.settled_at.isoformat() if db_escrow.settled_at else None,
    }
@router.get("/reconciliation/status")
async def reconciliation_status(db: Session = Depends(get_db)):
    """对账状态（从 jobs router）"""
    from ..models.db_models import EscrowDB
    
    settled = db.query(EscrowDB).filter(
        EscrowDB.status == EscrowStatusDB.SETTLED
    ).count()
    
    total = db.query(EscrowDB).count()
    
    return {
        "total_escrows": total,
        "settled_escrows": settled,
        "pending_escrows": total - settled,
        "reconciliation_needed": settled > 0,
        "dual_ledger_enabled": True,
        "local_ledger": "SQLite",
        "chain_ledger": "Escrow.sol (Polygon Amoy)"
    }


@router.post("/{job_id}/prelock")
async def prelock_job(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Pre-lock Job (DCM v3.1)
    
    触发 Job 的 Pre-lock 状态，设置过期时间
    Node Agent 收到 Pre-lock 后需要在 TTL 内发送 ACK
    """
    from datetime import datetime, timedelta
    
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 检查状态 (只有 MATCHED 状态可以 Pre-lock)
    if db_job.status != JobStatusDB.MATCHED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot prelock job in status: {db_job.status}"
        )
    
    # Pre-lock TTL: 30 秒
    PRELOCK_TTL_SECONDS = 30
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=PRELOCK_TTL_SECONDS)
    
    # 更新 Job 状态 (数据库)
    db_job.status = JobStatusDB.PRE_LOCKED
    db_job.pre_locked_at = now
    db_job.pre_lock_expires_at = expires_at
    
    # 更新内存服务的 Job 状态
    memory_job = matching_service._pending_jobs.get(job_id)
    if memory_job:
        memory_job.status = JobStatus.PRE_LOCKED
        memory_job.pre_locked_at = now
        memory_job.pre_lock_expires_at = expires_at
    
    db.commit()
    
    return {
        "job_id": job_id,
        "status": "pre_locked",
        "pre_locked_at": now.isoformat(),
        "pre_lock_expires_at": expires_at.isoformat(),
        "ttl_seconds": PRELOCK_TTL_SECONDS,
    }


@router.post("/{job_id}/prelock/ack")
async def prelock_ack(
    job_id: str,
    req: PreLockACKRequest,
    db: Session = Depends(get_db)
):
    """
    Pre-lock ACK (DCM v3.1)
    
    Node Agent 确认 Pre-lock，Job 状态变为 RESERVED
    """
    from datetime import datetime
    
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 检查状态
    if db_job.status != JobStatusDB.PRE_LOCKED:
        raise HTTPException(
            status_code=400,
            detail=f"Job not in pre_locked status: {db_job.status}"
        )
    
    # 检查是否过期
    if db_job.pre_lock_expires_at and datetime.utcnow() > db_job.pre_lock_expires_at:
        # 已过期，释放 Pre-lock
        db_job.status = JobStatusDB.MATCHED
        db_job.pre_locked_at = None
        db_job.pre_lock_expires_at = None
        
        # 更新内存服务
        memory_job = matching_service._pending_jobs.get(job_id)
        if memory_job:
            memory_job.status = JobStatus.MATCHED
            memory_job.pre_locked_at = None
            memory_job.pre_lock_expires_at = None
        
        db.commit()
        
        return {
            "job_id": job_id,
            "status": "expired",
            "message": "Pre-lock expired, job returned to matched"
        }
    
    # 确认 Pre-lock
    db_job.status = JobStatusDB.RESERVED
    db_job.pre_locked_at = None
    db_job.pre_lock_expires_at = None
    
    # 更新内存服务
    memory_job = matching_service._pending_jobs.get(job_id)
    if memory_job:
        memory_job.status = JobStatus.RESERVED
        memory_job.pre_locked_at = None
        memory_job.pre_lock_expires_at = None
    
    db.commit()
    
    return {
        "job_id": job_id,
        "status": "reserved",
        "message": "Pre-lock confirmed, job reserved"
    }


@router.post("/{job_id}/prelock/release")
async def release_prelock(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    释放 Pre-lock (DCM v3.1)
    
    将 Job 状态从 PRE_LOCKED 恢复到 MATCHED
    """
    from datetime import datetime
    
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if db_job.status != JobStatusDB.PRE_LOCKED:
        raise HTTPException(
            status_code=400,
            detail=f"Job not in pre_locked status: {db_job.status}"
        )
    
    # 释放 Pre-lock
    db_job.status = JobStatusDB.MATCHED
    db_job.pre_locked_at = None
    db_job.pre_lock_expires_at = None
    
    # 更新内存服务
    memory_job = matching_service._pending_jobs.get(job_id)
    if memory_job:
        memory_job.status = JobStatus.MATCHED
        memory_job.pre_locked_at = None
        memory_job.pre_lock_expires_at = None
    
    db.commit()
    
    return {
        "job_id": job_id,
        "status": "matched",
        "message": "Pre-lock released, job returned to matched"
    }


@router.post("/prelock/cleanup")
async def cleanup_expired_prelocks(
    db: Session = Depends(get_db)
):
    """
    清理过期的 Pre-lock (DCM v3.1)
    
    将所有超时的 PRE_LOCKED Job 状态恢复到 MATCHED
    由定时任务调用
    """
    from datetime import datetime
    
    # 查找所有过期的 Pre-lock
    expired_jobs = db.query(JobDB).filter(
        JobDB.status == JobStatusDB.PRE_LOCKED,
        JobDB.pre_lock_expires_at < datetime.utcnow()
    ).all()
    
    released_count = 0
    for job in expired_jobs:
        job.status = JobStatusDB.MATCHED
        job.pre_locked_at = None
        job.pre_lock_expires_at = None
        
        # 更新内存服务
        memory_job = matching_service._pending_jobs.get(job.job_id)
        if memory_job:
            memory_job.status = JobStatus.MATCHED
            memory_job.pre_locked_at = None
            memory_job.pre_lock_expires_at = None
        
        released_count += 1
    
    db.commit()
    
    return {
        "released_count": released_count,
        "message": f"Released {released_count} expired pre-locks"
    }


@router.get("")
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """列出 Job 列表"""
    job_repo = JobRepository(db)
    
    if status:
        try:
            job_status = JobStatus(status)
            jobs = job_repo.list_by_status(job_status, limit, offset)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    else:
        # 简化：返回所有 Jobs
        jobs = db.query(JobDB).offset(offset).limit(limit).all()
    
    return {
        "items": [
            {
                "job_id": job.job_id,
                "model": job.model,
                "status": _safe_status(job.status),
                "bid_price": job.bid_price,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            }
            for job in jobs
        ],
        "total": db.query(JobDB).count(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats/summary")
async def get_job_stats(db: Session = Depends(get_db)):
    """获取 Job 统计"""
    total = db.query(JobDB).count()
    pending = db.query(JobDB).filter(JobDB.status == JobStatusDB.PENDING).count()
    matched = db.query(JobDB).filter(JobDB.status == JobStatusDB.MATCHED).count()
    completed = db.query(JobDB).filter(JobDB.status == JobStatusDB.COMPLETED).count()
    failed = db.query(JobDB).filter(JobDB.status == JobStatusDB.FAILED).count()
    
    return {
        "total": total,
        "by_status": {
            "pending": pending,
            "matched": matched,
            "completed": completed,
            "failed": failed,
        },
        "pending_in_queue": matching_service.get_pending_jobs_count(),
    }





@router.get("/debug/routes")
async def debug_routes():
    """调试端点：列出所有 jobs 路由"""
    routes = []
    for route in jobs_router.routes:
        routes.append({
            "path": route.path,
            "methods": list(route.methods) if hasattr(route, 'methods') else ['GET']
        })
    return {"routes": routes}
