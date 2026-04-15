"""
Disputes API - F7: 争议与申诉
来源: Function/F7
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from ..database import get_db
from ..services import stake_service
from ..models.db_models import DisputeDB, AppealDB, NodeDB
from src.exceptions import (
    ErrorCode,
    HTTPException,
    raise_not_found,
    raise_invalid_status,
    raise_validation_error,
    raise_bad_request,
    raise_internal_error,
)


router = APIRouter(prefix="/api/v1/disputes", tags=["disputes"])


class AppealCreate(BaseModel):
    """申诉创建请求"""
    evidence: str  # Base64 encoded logs
    message: str


# ===== 争议接口 =====

@router.get("/{dispute_id}")
async def get_dispute(
    dispute_id: str,
    db: Session = Depends(get_db)
):
    """获取争议详情"""
    db_dispute = db.query(DisputeDB).filter(
        DisputeDB.dispute_id == dispute_id
    ).first()
    
    if not db_dispute:
        raise_not_found("dispute", dispute_id)
    
    # 获取节点信息
    db_node = db.query(NodeDB).filter(
        NodeDB.node_id == db_dispute.node_id
    ).first()
    
    return {
        "dispute_id": db_dispute.dispute_id,
        "node_id": db_dispute.node_id,
        "node_name": db_node.gpu_type if db_node else None,
        "match_ids": db_dispute.match_ids.split(",") if db_dispute.match_ids else [],
        "reason": db_dispute.reason,
        "status": db_dispute.status,
        "created_at": db_dispute.created_at.isoformat() if db_dispute.created_at else None,
        "frozen_at": db_dispute.frozen_at.isoformat() if db_dispute.frozen_at else None,
        "appeal_deadline": db_dispute.appeal_deadline.isoformat() if db_dispute.appeal_deadline else None,
    }


@router.get("/node/{node_id}")
async def get_node_disputes(
    node_id: str,
    db: Session = Depends(get_db)
):
    """获取节点的所有争议"""
    disputes = db.query(DisputeDB).filter(
        DisputeDB.node_id == node_id
    ).all()
    
    return {
        "items": [
            {
                "dispute_id": d.dispute_id,
                "reason": d.reason,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "frozen_at": d.frozen_at.isoformat() if d.frozen_at else None,
            }
            for d in disputes
        ],
        "total": len(disputes),
    }


@router.get("")
async def list_disputes(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """列出争议列表"""
    query = db.query(DisputeDB)
    
    if status:
        query = query.filter(DisputeDB.status == status)
    
    total = query.count()
    disputes = query.offset(offset).limit(limit).all()
    
    return {
        "items": [
            {
                "dispute_id": d.dispute_id,
                "node_id": d.node_id,
                "reason": d.reason,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in disputes
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ===== 申诉接口 =====

@router.post("/{dispute_id}/appeals")
async def submit_appeal(
    dispute_id: str,
    appeal: AppealCreate,
    db: Session = Depends(get_db)
):
    """
    提交申诉
    
    MVP 阶段仅记录，不裁决
    """
    # 检查争议是否存在
    db_dispute = db.query(DisputeDB).filter(
        DisputeDB.dispute_id == dispute_id
    ).first()
    
    if not db_dispute:
        raise_not_found("dispute", dispute_id)
    
    # 检查是否已提交申诉
    existing = db.query(AppealDB).filter(
        AppealDB.dispute_id == dispute_id
    ).first()
    
    if existing:
        raise_bad_request("Appeal already submitted")
    
    # 检查是否超过申诉期限
    if db_dispute.appeal_deadline and datetime.utcnow() > db_dispute.appeal_deadline:
        raise_bad_request("Appeal deadline passed")
    
    # 创建申诉记录
    appeal_id = f"appeal_{dispute_id}_{datetime.utcnow().timestamp()}"
    db_appeal = AppealDB(
        appeal_id=appeal_id,
        dispute_id=dispute_id,
        node_id=db_dispute.node_id,
        evidence=appeal.evidence,
        message=appeal.message,
        status="submitted",
    )
    
    # 更新争议状态
    db_dispute.status = "under_review"
    
    db.add(db_appeal)
    db.commit()
    db.refresh(db_appeal)
    
    return {
        "appeal_id": appeal_id,
        "dispute_id": dispute_id,
        "status": "submitted",
        "message": "Appeal submitted successfully. MVP: No automatic resolution.",
    }


@router.get("/{dispute_id}/appeals/{appeal_id}")
async def get_appeal(
    dispute_id: str,
    appeal_id: str,
    db: Session = Depends(get_db)
):
    """获取申诉详情"""
    db_appeal = db.query(AppealDB).filter(
        AppealDB.appeal_id == appeal_id,
        AppealDB.dispute_id == dispute_id,
    ).first()
    
    if not db_appeal:
        raise_not_found("Appeal not found", "Appeal not found")
    
    return {
        "appeal_id": db_appeal.appeal_id,
        "dispute_id": db_appeal.dispute_id,
        "node_id": db_appeal.node_id,
        "evidence": db_appeal.evidence,
        "message": db_appeal.message,
        "status": db_appeal.status,
        "submitted_at": db_appeal.submitted_at.isoformat() if db_appeal.submitted_at else None,
        "reviewed_at": db_appeal.reviewed_at.isoformat() if db_appeal.reviewed_at else None,
    }


@router.get("/appeals")
async def list_appeals(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """列出申诉列表"""
    query = db.query(AppealDB)
    
    if status:
        query = query.filter(AppealDB.status == status)
    
    total = query.count()
    appeals = query.offset(offset).limit(limit).all()
    
    return {
        "items": [
            {
                "appeal_id": a.appeal_id,
                "dispute_id": a.dispute_id,
                "node_id": a.node_id,
                "status": a.status,
                "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            }
            for a in appeals
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ===== 统计接口 =====

@router.get("/stats/summary")
async def get_dispute_stats(db: Session = Depends(get_db)):
    """获取争议统计"""
    total = db.query(DisputeDB).count()
    pending = db.query(DisputeDB).filter(DisputeDB.status == "pending").count()
    frozen = db.query(DisputeDB).filter(DisputeDB.status == "frozen").count()
    under_review = db.query(DisputeDB).filter(DisputeDB.status == "under_review").count()
    
    total_appeals = db.query(AppealDB).count()
    pending_appeals = db.query(AppealDB).filter(AppealDB.status == "submitted").count()
    
    return {
        "disputes": {
            "total": total,
            "pending": pending,
            "frozen": frozen,
            "under_review": under_review,
        },
        "appeals": {
            "total": total_appeals,
            "pending": pending_appeals,
        },
    }
