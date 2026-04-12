"""
Stake Service - F7: Stake 管理与争议处理
来源: PRD 0.2 Section 5.3 & Function/F7

MVP 阶段: 冻结不扣除，仅记录
"""

from typing import Optional, List
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel
from ..models import Node, NodeStatus


class DisputeStatus(str, Enum):
    """争议状态"""
    PENDING = "pending"      # 等待申诉
    UNDER_REVIEW = "under_review"  # 审核中
    FROZEN = "frozen"       # 已冻结
    RESOLVED = "resolved"   # 已解决（MVP 不实现）


class StakeRecord(BaseModel):
    """Stake 记录"""
    node_id: str
    amount: float
    tx_hash: str
    status: str  # active, frozen, released
    created_at: datetime


class Dispute(BaseModel):
    """争议记录"""
    dispute_id: str
    node_id: str
    match_ids: List[str]
    reason: str
    status: DisputeStatus
    created_at: datetime
    frozen_at: Optional[datetime] = None
    appeal_deadline: Optional[datetime] = None  # 冻结后 48h


class Appeal(BaseModel):
    """申诉"""
    appeal_id: str
    dispute_id: str
    node_id: str
    evidence: str  # base64 encoded logs
    message: str
    submitted_at: datetime
    status: str  # submitted, reviewed, rejected, accepted


class StakeService:
    """Stake 管理服务（MVP 阶段简化版）"""
    
    def __init__(self):
        # Stake 记录
        self._stake_records: dict[str, StakeRecord] = {}
        # 争议记录
        self._disputes: dict[str, Dispute] = {}
        # 申诉记录
        self._appeals: dict[str, Appeal] = {}
    
    def calculate_stake_required(self, vram_gb: int) -> float:
        """计算所需 Stake"""
        if vram_gb < 24:
            return 50.0   # Personal
        elif vram_gb <= 80:
            return 200.0  # Professional
        else:
            return 1000.0  # Data Center
    
    def deposit_stake(self, node_id: str, amount: float, tx_hash: str) -> StakeRecord:
        """
        确认 Stake 存款
        实际存款通过链上合约完成，这里只记录确认
        """
        record = StakeRecord(
            node_id=node_id,
            amount=amount,
            tx_hash=tx_hash,
            status="active",
            created_at=datetime.utcnow(),
        )
        self._stake_records[node_id] = record
        return record
    
    def get_stake_record(self, node_id: str) -> Optional[StakeRecord]:
        """获取 Stake 记录"""
        return self._stake_records.get(node_id)
    
    def freeze_stake(self, node_id: str, reason: str, 
                     match_ids: List[str]) -> Dispute:
        """
        冻结 Stake（MVP 阶段不扣除）
        
        触发条件:
        - Layer 2 检测到异常（相似度 < 0.65）
        - 连续 3 次抽样不一致
        """
        dispute = Dispute(
            dispute_id=f"dispute_{node_id}_{len(self._disputes)}",
            node_id=node_id,
            match_ids=match_ids,
            reason=reason,
            status=DisputeStatus.FROZEN,
            created_at=datetime.utcnow(),
            frozen_at=datetime.utcnow(),
            appeal_deadline=datetime.utcnow() + timedelta(hours=48),
        )
        
        self._disputes[dispute.dispute_id] = dispute
        
        # 更新 Stake 状态
        if node_id in self._stake_records:
            self._stake_records[node_id].status = "frozen"
        
        return dispute
    
    def submit_appeal(self, dispute_id: str, node_id: str,
                     evidence: str, message: str) -> Appeal:
        """
        提交申诉（MVP 阶段仅记录）
        """
        appeal = Appeal(
            appeal_id=f"appeal_{node_id}_{len(self._appeals)}",
            dispute_id=dispute_id,
            node_id=node_id,
            evidence=evidence,
            message=message,
            submitted_at=datetime.utcnow(),
            status="submitted",
        )
        
        self._appeals[appeal.appeal_id] = appeal
        
        # 更新争议状态
        dispute = self._disputes.get(dispute_id)
        if dispute:
            dispute.status = DisputeStatus.UNDER_REVIEW
        
        return appeal
    
    def get_dispute(self, dispute_id: str) -> Optional[Dispute]:
        """获取争议记录"""
        return self._disputes.get(dispute_id)
    
    def get_node_disputes(self, node_id: str) -> List[Dispute]:
        """获取节点的所有争议"""
        return [
            d for d in self._disputes.values()
            if d.node_id == node_id
        ]
    
    def is_node_frozen(self, node_id: str) -> bool:
        """检查节点是否被冻结"""
        dispute = self.get_node_disputes(node_id)
        return any(d.status == DisputeStatus.FROZEN for d in dispute)
    
    def get_stats(self) -> dict:
        """获取统计数据"""
        return {
            "total_stakes": len(self._stake_records),
            "active_stakes": sum(1 for r in self._stake_records.values() if r.status == "active"),
            "frozen_stakes": sum(1 for r in self._stake_records.values() if r.status == "frozen"),
            "total_disputes": len(self._disputes),
            "pending_appeals": sum(1 for a in self._appeals.values() if a.status == "submitted"),
        }


# 单例
stake_service = StakeService()
