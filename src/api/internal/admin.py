from src.exceptions import (
    ErrorCode,
    HTTPException,
    raise_not_found,
    raise_invalid_status,
    raise_validation_error,
    raise_bad_request,
    raise_internal_error,
)

"""
Internal API - 管理接口
包含: Stake、争议、统计、数据库操作
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Any
from datetime import datetime

from ...database import get_db
from ...models.db_models import JobDB, EscrowDB, MatchDB, NodeDB, DisputeDB
from ...models import NodeStatus
from ...repositories import JobRepository, NodeRepository
from ...services import stake_service, retry_service, verification_service, matching_service

router = APIRouter(prefix="", tags=["internal/admin"])


# ===== 请求模型 =====

class FreezeStakeRequest(BaseModel):
    """冻结 Stake 请求"""
    node_id: str
    reason: str
    match_ids: List[str]


# ===== Stake/争议接口 =====

@router.post("/stake/freeze")
async def freeze_stake_endpoint(
    request: FreezeStakeRequest,
    db: Session = Depends(get_db)
):
    """
    冻结节点 Stake（内部接口）
    """
    dispute = stake_service.freeze_stake(
        node_id=request.node_id,
        reason=request.reason,
        match_ids=request.match_ids,
    )
    
    # 保存争议到数据库
    db_dispute = DisputeDB(
        dispute_id=dispute.dispute_id,
        node_id=dispute.node_id,
        match_ids=",".join(dispute.match_ids),
        reason=dispute.reason,
        status="frozen",
        frozen_at=dispute.frozen_at,
        appeal_deadline=dispute.appeal_deadline,
    )
    db.add(db_dispute)
    
    # 节点状态设为 locked
    node_repo = NodeRepository(db)
    node_repo.update(request.node_id, status=NodeStatus.LOCKED)
    
    db.commit()
    
    # 更新内存服务
    matching_service.update_node_status(request.node_id, NodeStatus.LOCKED)
    
    return {
        "dispute_id": dispute.dispute_id,
        "node_id": request.node_id,
        "status": dispute.status.value,
        "appeal_deadline": dispute.appeal_deadline.isoformat() if dispute.appeal_deadline else None,
    }


@router.get("/disputes/{dispute_id}")
async def get_dispute_endpoint(
    dispute_id: str,
    db: Session = Depends(get_db)
):
    """获取争议详情"""
    dispute = stake_service.get_dispute(dispute_id)
    
    if not dispute:
        raise_not_found("dispute", dispute_id)
    
    return {
        "dispute_id": dispute.dispute_id,
        "node_id": dispute.node_id,
        "match_ids": dispute.match_ids,
        "reason": dispute.reason,
        "status": dispute.status.value,
        "created_at": dispute.created_at.isoformat(),
        "frozen_at": dispute.frozen_at.isoformat() if dispute.frozen_at else None,
        "appeal_deadline": dispute.appeal_deadline.isoformat() if dispute.appeal_deadline else None,
    }


# ===== 统计接口 =====

@router.get("/stats/failures")
async def get_failure_stats_endpoint():
    """获取失败统计"""
    return retry_service.get_failure_stats()


@router.get("/stats/verification")
async def get_verification_stats_endpoint():
    """获取验证统计"""
    return {
        "total_violations": sum(verification_service._node_violations.values()),
        "by_node": verification_service._node_violations,
    }


@router.get("/debug/db-status")
async def debug_db_status(db: Session = Depends(get_db)):
    """调试端点: 检查数据库状态"""
    return {
        "jobs": db.query(JobDB).count(),
        "escrows": db.query(EscrowDB).count(),
        "matches": db.query(MatchDB).count(),
        "nodes": db.query(NodeDB).count(),
        "recent_jobs": [
            {"job_id": j.job_id, "status": j.status, "bid_price": j.bid_price}
            for j in db.query(JobDB).order_by(JobDB.created_at.desc()).limit(3).all()
        ],
        "recent_escrows": [
            {"escrow_id": e.escrow_id, "job_id": e.job_id, "match_id": e.match_id, "status": e.status}
            for e in db.query(EscrowDB).order_by(EscrowDB.created_at.desc()).limit(3).all()
        ],
        "recent_matches": [
            {"match_id": m.match_id, "job_id": m.job_id, "node_id": m.node_id}
            for m in db.query(MatchDB).order_by(MatchDB.matched_at.desc()).limit(3).all()
        ],
    }


# ===== 数据库接口 =====

@router.post("/db/migrate")
async def db_migrate(db: Session = Depends(get_db)):
    """
    数据库迁移：添加新列到现有表
    
    注意: 仅限开发环境使用
    """
    from sqlalchemy import text
    import logging
    logger = logging.getLogger(__name__)
    
    migrations = [
        ("nodes", "cluster_id", "VARCHAR(50)"),
        ("jobs", "max_latency", "INTEGER NOT NULL DEFAULT 30000"),
        ("jobs", "user_id", "VARCHAR(36)"),
        ("jobs", "input_tokens", "INTEGER NOT NULL DEFAULT 10"),
        ("jobs", "output_tokens_limit", "INTEGER NOT NULL DEFAULT 100"),
        ("jobs", "bid_price", "FLOAT NOT NULL DEFAULT 0.001"),
    ]
    
    results = []
    for table, column, col_type in migrations:
        try:
            # 检查列是否存在
            result = db.execute(text(f"PRAGMA table_info({table})"))
            columns = [row[1] for row in result]
            
            if column not in columns:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                db.commit()
                results.append({"table": table, "column": column, "status": "added"})
                logger.info(f"Migration: Added {column} to {table}")
            else:
                results.append({"table": table, "column": column, "status": "exists"})
        except Exception as e:
            results.append({"table": table, "column": column, "status": "error", "error": str(e)})
            logger.error(f"Migration failed: {e}")
    
    return {"migrations": results}


@router.get("/db/check/{table}")
async def db_check_table(table: str, db: Session = Depends(get_db)):
    """检查表结构"""
    from sqlalchemy import text
    result = db.execute(text(f"PRAGMA table_info({table})"))
    columns = [{"cid": row[0], "name": row[1], "type": row[2]} for row in result]
    
    # 也检查索引
    indexes = db.execute(text(f"PRAGMA index_list({table})"))
    index_list = [{"name": row[1]} for row in indexes]
    
    return {"table": table, "columns": columns, "indexes": index_list}
