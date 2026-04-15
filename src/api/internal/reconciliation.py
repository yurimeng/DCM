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
Internal API - 对账接口
包含: 孤儿节点检查、双账本对账
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from datetime import datetime

from ...database import get_db, SessionLocal
from ...models.db_models import EscrowDB, EscrowStatusDB, NodeDB
from ...repositories import NodeRepository, UserRepository

router = APIRouter(prefix="", tags=["internal/reconciliation"])


@router.get("/nodes/orphans")
async def get_orphan_nodes():
    """
    获取孤儿节点（节点有user_id但用户node_ids中没有该节点）
    GET /internal/v1/nodes/orphans
    """
    import json
    
    db = SessionLocal()
    try:
        node_repo = NodeRepository(db)
        user_repo = UserRepository(db)
        
        orphan_nodes = []
        
        # Get all nodes with user_id
        nodes = db.query(NodeDB).filter(NodeDB.user_id.isnot(None)).all()
        
        for node in nodes:
            user_id = node.user_id
            node_id = node.node_id
            
            # Check if user exists and has this node in node_ids
            user = user_repo.get(user_id)
            if not user:
                # User not found
                orphan_nodes.append({
                    "node_id": node_id,
                    "user_id": user_id,
                    "reason": "user_not_found",
                    "gpu_type": node.gpu_type,
                    "status": node.status,
                })
            else:
                user_node_ids = json.loads(user.node_ids or "[]")
                if node_id not in user_node_ids:
                    # User doesn't have this node in node_ids
                    orphan_nodes.append({
                        "node_id": node_id,
                        "user_id": user_id,
                        "reason": "node_not_in_user_list",
                        "gpu_type": node.gpu_type,
                        "status": node.status,
                        "user_node_ids": user_node_ids,
                    })
        
        return {
            "orphan_count": len(orphan_nodes),
            "orphan_nodes": orphan_nodes,
        }
    finally:
        db.close()


# ===== 对账接口 =====

@router.get("/reconciliation/check")
async def reconciliation_check(
    job_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    对账检查：比较本地 SQLite 与链上记录
    
    Query Params:
        job_id: 可选，指定 Job 进行对账；不传则对所有记录
    
    Returns:
        对账结果
    """
    from ...services.chain_sync import chain_sync_service
    
    if job_id:
        # 单条对账
        db_escrow = db.query(EscrowDB).filter(
            EscrowDB.job_id == job_id
        ).first()
        
        if not db_escrow:
            raise_not_found("escrow", job_id)
        
        # 获取链上记录
        chain_record = chain_sync_service.get_chain_settlement(job_id)
        
        return {
            "job_id": job_id,
            "local": {
                "actual_cost": db_escrow.actual_cost,
                "node_earn": db_escrow.node_earn,
                "platform_fee": db_escrow.platform_fee,
                "refund_amount": db_escrow.refund_amount,
                "status": str(db_escrow.status),
                "settled": db_escrow.status == EscrowStatusDB.SETTLED
            },
            "chain": chain_record.__dict__ if chain_record else None,
            "verified": chain_record is not None and chain_record.settled,
            "method": "sqlite_primary" if chain_record else "chain_fallback"
        }
    else:
        # 全量对账
        settled_escrows = db.query(EscrowDB).filter(
            EscrowDB.status == EscrowStatusDB.SETTLED
        ).all()
        
        local_records = [
            {
                "job_id": e.job_id,
                "actual_cost": e.actual_cost,
                "node_earn": e.node_earn,
                "platform_fee": e.platform_fee,
                "refund_amount": e.refund_amount
            }
            for e in settled_escrows
        ]
        
        result = chain_sync_service.reconcile(local_records)
        
        return {
            "total": result.total_records,
            "matched": result.matched,
            "mismatched": result.mismatched,
            "missing_on_chain": result.missing_on_chain,
            "missing_local": result.missing_local,
            "match_rate": f"{result.matched / max(result.total_records, 1) * 100:.2f}%",
            "details": result.details[:20]  # 最多返回 20 条
        }


@router.get("/reconciliation/verify/{job_id}")
async def verify_settlement(
    job_id: str,
    result_hash: str,
    actual_cost: float,
    db: Session = Depends(get_db)
):
    """
    验证特定结算记录的完整性
    
    Args:
        job_id: Job ID
        result_hash: 期望的结果哈希
        actual_cost: 期望的费用
    
    Returns:
        验证结果
    """
    from ...services.chain_sync import chain_sync_service
    
    verified, reason = chain_sync_service.verify_settlement(
        job_id, result_hash, actual_cost
    )
    
    return {
        "job_id": job_id,
        "verified": verified,
        "reason": reason,
        "verified_at": datetime.utcnow().isoformat()
    }
