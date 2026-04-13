"""
Jobs API - F1: Job 提交与管理系统
来源: Function/F1
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional, List

from ..database import get_db
from ..models import Job, JobCreate, JobResponse, JobStatus, JobDB
from ..models.db_models import JobStatusDB, EscrowDB, EscrowStatusDB
from ..repositories import JobRepository, EscrowRepository
from ..services import matching_service, escrow_service
from config import settings

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
    match = matching_service.trigger_match(job.job_id)
    
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
        "final_price": db_job.final_price,
        "retry_count": db_job.retry_count,
        "escrow": {
            "locked_amount": db_escrow.locked_amount if db_escrow else None,
            "spent_amount": db_escrow.spent_amount if db_escrow else None,
            "refund_amount": db_escrow.refund_amount if db_escrow else None,
            "status": _safe_status(db_escrow.status) if db_escrow else None,
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
        "settled_at": db_escrow.settled_at.isoformat() if db_escrow.settled_at else None,
        "refunded_at": db_escrow.refunded_at.isoformat() if db_escrow.refunded_at else None,
        "actual_tokens": db_escrow.actual_tokens,
        "actual_cost": db_escrow.actual_cost,
        "platform_fee": db_escrow.platform_fee,
        "node_earn": db_escrow.node_earn,
        "refund_reason": db_escrow.refund_reason,
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
