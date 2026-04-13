"""
Repository Layer - Database Access Abstraction
使用 Repository Pattern 解耦业务逻辑和数据库
"""

from typing import Optional, List
from datetime import datetime
import json
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from .models import (
    JobDB, NodeDB, MatchDB, EscrowDB,
    StakeRecordDB, DisputeDB, AppealDB,
    JobStatusDB, NodeStatusDB, EscrowStatusDB
)
from .models.job import Job, JobStatus
from .models.node import Node, NodeStatus, NodeTier
from .models.match import Match
from .models.escrow import Escrow, EscrowStatus


class JobRepository:
    """Job 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, job: Job) -> JobDB:
        """创建 Job"""
        db_job = JobDB(
            job_id=job.job_id,
            model=job.model,
            input_tokens=job.input_tokens,
            output_tokens_limit=job.output_tokens_limit,
            max_latency=job.max_latency,
            bid_price=job.bid_price,
            callback_url=job.callback_url,
            status=JobStatusDB[job.status.name.upper()],
            retry_count=job.retry_count,
            max_retries=job.max_retries,
        )
        self.db.add(db_job)
        self.db.commit()
        self.db.refresh(db_job)
        return db_job
    
    def get(self, job_id: str) -> Optional[JobDB]:
        """获取 Job"""
        return self.db.query(JobDB).filter(JobDB.job_id == job_id).first()
    
    def update(self, job_id: str, **kwargs) -> Optional[JobDB]:
        """更新 Job"""
        from datetime import datetime
        
        job = self.get(job_id)
        if not job:
            return None
        
        for key, value in kwargs.items():
            if hasattr(job, key):
                # 枚举转换
                if key == "status" and isinstance(value, JobStatus):
                    value = JobStatusDB[value.name.upper()]
                    # 自动设置时间戳
                    if value == JobStatusDB.MATCHED and not job.matched_at:
                        job.matched_at = datetime.utcnow()
                    elif value == JobStatusDB.COMPLETED and not job.completed_at:
                        job.completed_at = datetime.utcnow()
                setattr(job, key, value)
        
        self.db.commit()
        self.db.refresh(job)
        return job
    
    def list_pending(self, limit: int = 100) -> List[JobDB]:
        """列出待撮合的 Jobs"""
        return self.db.query(JobDB).filter(
            JobDB.status == JobStatusDB.PENDING
        ).order_by(
            desc(JobDB.bid_price),
            asc(JobDB.created_at)
        ).limit(limit).all()
    
    def list_by_status(self, status: JobStatus, limit: int = 100, offset: int = 0) -> List[JobDB]:
        """按状态列出 Jobs"""
        return self.db.query(JobDB).filter(
            JobDB.status == JobStatusDB[status.name.upper()]
        ).offset(offset).limit(limit).all()
    
    def to_model(self, db_job: JobDB) -> Job:
        """转换为 Pydantic 模型"""
        return Job(
            job_id=db_job.job_id,
            model=db_job.model,
            input_tokens=db_job.input_tokens,
            output_tokens_limit=db_job.output_tokens_limit,
            max_latency=db_job.max_latency,
            bid_price=db_job.bid_price,
            callback_url=db_job.callback_url,
            status=JobStatus[db_job.status.name.lower()],
            created_at=db_job.created_at,
            matched_at=db_job.matched_at,
            completed_at=db_job.completed_at,
            actual_output_tokens=db_job.actual_output_tokens,
            final_price=db_job.final_price,
            result=db_job.result,
            retry_count=db_job.retry_count,
            max_retries=db_job.max_retries,
        )


class NodeRepository:
    """Node 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, node: Node) -> NodeDB:
        """创建 Node"""
        db_node = NodeDB(
            node_id=node.node_id,
            gpu_type=node.gpu_type,
            vram_gb=node.vram_gb,
            model_support=json.dumps(node.model_support),
            ask_price=node.ask_price,
            avg_latency=node.avg_latency,
            region=node.region,
            status=NodeStatusDB[node.status.name.upper()],
            stake_amount=node.stake_amount,
            stake_required=node.stake_required,
            stake_tier=node.stake_tier.value,
        )
        self.db.add(db_node)
        self.db.commit()
        self.db.refresh(db_node)
        return db_node
    
    def get(self, node_id: str) -> Optional[NodeDB]:
        """获取 Node"""
        return self.db.query(NodeDB).filter(NodeDB.node_id == node_id).first()
    
    def update(self, node_id: str, **kwargs) -> Optional[NodeDB]:
        """更新 Node"""
        node = self.get(node_id)
        if not node:
            return None
        
        for key, value in kwargs.items():
            if hasattr(node, key):
                # 枚举转换
                if key == "status" and isinstance(value, NodeStatus):
                    value = NodeStatusDB[value.name.upper()]
                setattr(node, key, value)
        
        self.db.commit()
        self.db.refresh(node)
        return node
    
    def list_online(self) -> List[NodeDB]:
        """列出在线节点"""
        return self.db.query(NodeDB).filter(
            NodeDB.status == NodeStatusDB.ONLINE
        ).order_by(asc(NodeDB.ask_price)).all()
    
    def list_all(self, limit: int = 100, offset: int = 0) -> List[NodeDB]:
        """列出所有节点"""
        return self.db.query(NodeDB).offset(offset).limit(limit).all()
    
    def update_heartbeat(self, node_id: str) -> Optional[NodeDB]:
        """更新心跳时间"""
        node = self.get(node_id)
        if node:
            node.last_heartbeat = datetime.utcnow()
            self.db.commit()
            self.db.refresh(node)
        return node
    
    def to_model(self, db_node: NodeDB) -> Node:
        """转换为 Pydantic 模型"""
        return Node(
            node_id=db_node.node_id,
            gpu_type=db_node.gpu_type,
            vram_gb=db_node.vram_gb,
            model_support=json.loads(db_node.model_support),
            ask_price=db_node.ask_price,
            avg_latency=db_node.avg_latency,
            region=db_node.region,
            status=NodeStatus[db_node.status.name.lower()],
            stake_amount=db_node.stake_amount,
            stake_required=db_node.stake_required,
            stake_tier=NodeTier(db_node.stake_tier),
            registered_at=db_node.registered_at,
            last_heartbeat=db_node.last_heartbeat,
        )


class MatchRepository:
    """Match 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, match: Match) -> MatchDB:
        """创建 Match"""
        db_match = MatchDB(
            match_id=match.match_id,
            job_id=match.job_id,
            node_id=match.node_id,
            locked_price=match.locked_price,
            matched_at=match.matched_at,
            retry_count=match.retry_count,
            original_match_id=match.original_match_id,
        )
        self.db.add(db_match)
        self.db.commit()
        self.db.refresh(db_match)
        return db_match
    
    def get(self, match_id: str) -> Optional[MatchDB]:
        """获取 Match"""
        return self.db.query(MatchDB).filter(MatchDB.match_id == match_id).first()
    
    def get_by_job(self, job_id: str) -> Optional[MatchDB]:
        """根据 Job ID 获取 Match"""
        return self.db.query(MatchDB).filter(MatchDB.job_id == job_id).first()
    
    def update(self, match_id: str, **kwargs) -> Optional[MatchDB]:
        """更新 Match"""
        match = self.get(match_id)
        if not match:
            return None
        
        for key, value in kwargs.items():
            if hasattr(match, key):
                setattr(match, key, value)
        
        self.db.commit()
        self.db.refresh(match)
        return match
    
    def list_recent(self, limit: int = 100) -> List[MatchDB]:
        """列出最近的 Matches"""
        return self.db.query(MatchDB).order_by(
            desc(MatchDB.matched_at)
        ).limit(limit).all()
    
    def to_model(self, db_match: MatchDB) -> Match:
        """转换为 Pydantic 模型"""
        return Match(
            match_id=db_match.match_id,
            job_id=db_match.job_id,
            node_id=db_match.node_id,
            locked_price=db_match.locked_price,
            matched_at=db_match.matched_at,
            result_hash=db_match.result_hash,
            actual_latency_ms=db_match.actual_latency_ms,
            verified=db_match.verified,
            verification_layer=db_match.verification_layer,
            layer2_consistency=db_match.layer2_consistency,
            settled=db_match.settled,
            settled_at=db_match.settled_at,
            retry_count=db_match.retry_count,
            original_match_id=db_match.original_match_id,
        )


class EscrowRepository:
    """Escrow 数据访问"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, escrow: Escrow) -> EscrowDB:
        """创建 Escrow"""
        db_escrow = EscrowDB(
            escrow_id=escrow.escrow_id,
            job_id=escrow.job_id,
            match_id=escrow.match_id,
            locked_amount=escrow.locked_amount,
            spent_amount=escrow.spent_amount,
            refund_amount=escrow.refund_amount,
            status=EscrowStatusDB[escrow.status.name.upper()],
        )
        self.db.add(db_escrow)
        self.db.commit()
        self.db.refresh(db_escrow)
        return db_escrow
    
    def get(self, escrow_id: str) -> Optional[EscrowDB]:
        """获取 Escrow"""
        return self.db.query(EscrowDB).filter(EscrowDB.escrow_id == escrow_id).first()
    
    def get_by_job(self, job_id: str) -> Optional[EscrowDB]:
        """根据 Job ID 获取 Escrow"""
        return self.db.query(EscrowDB).filter(EscrowDB.job_id == job_id).first()
    
    def get_by_match(self, match_id: str) -> Optional[EscrowDB]:
        """根据 Match ID 获取 Escrow"""
        return self.db.query(EscrowDB).filter(EscrowDB.match_id == match_id).first()
    
    def update(self, escrow_id: str, **kwargs) -> Optional[EscrowDB]:
        """更新 Escrow"""
        escrow = self.get(escrow_id)
        if not escrow:
            return None
        
        for key, value in kwargs.items():
            if hasattr(escrow, key):
                if key == "status" and isinstance(value, EscrowStatus):
                    value = EscrowStatusDB[value.name.upper()]
                setattr(escrow, key, value)
        
        self.db.commit()
        self.db.refresh(escrow)
        return escrow
    
    def to_model(self, db_escrow: EscrowDB) -> Escrow:
        """转换为 Pydantic 模型"""
        return Escrow(
            escrow_id=db_escrow.escrow_id,
            job_id=db_escrow.job_id,
            match_id=db_escrow.match_id,
            locked_amount=db_escrow.locked_amount,
            spent_amount=db_escrow.spent_amount,
            refund_amount=db_escrow.refund_amount,
            status=EscrowStatus[db_escrow.status.name.lower()],
            created_at=db_escrow.created_at,
            settled_at=db_escrow.settled_at,
            refunded_at=db_escrow.refunded_at,
            actual_tokens=db_escrow.actual_tokens,
            actual_cost=db_escrow.actual_cost,
            platform_fee=db_escrow.platform_fee,
            node_earn=db_escrow.node_earn,
            refund_reason=db_escrow.refund_reason,
        )
