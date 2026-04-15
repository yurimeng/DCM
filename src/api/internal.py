"""
Internal API - F3/F5/F6: 撮合、验证、结算内部接口
来源: Function/F3, F5, F6
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from ..database import get_db
from ..models.db_models import JobDB, MatchDB, EscrowDB, EscrowStatusDB
from ..models import JobStatus, EscrowStatus, NodeStatus
from ..repositories import JobRepository, MatchRepository, EscrowRepository, NodeRepository
from ..services import matching_service, escrow_service, verification_service, retry_service, stake_service
from ..services.retry import FailureType
from config import settings
from ..services.settlement_config import settlement_config

router = APIRouter(prefix="/internal/v1", tags=["internal"])


# ===== 健康检查 =====

@router.get("/health")
async def health_check():
    """
    健康检查端点
    
    GET /internal/v1/health
    
    用于 Render 健康检查
    """
    from ..services import matching_service
    
    return {
        "status": "healthy",
        "version": "0.1.0",
        "mvp_mode": True,
        "services": {
            "matching": matching_service.get_status(),
            "online_nodes": len(matching_service._online_nodes),
        }
    }


@router.get("/config/job")
async def get_job_config():
    """
    获取 Job 配置
    
    GET /internal/v1/config/job
    
    返回当前 Job 配置（从 job_config 读取）
    """
    from ..services.job_config import get_job_config
    
    config = get_job_config()
    return {
        "max_output_tokens": config.max_output_tokens,
        "max_input_tokens": config.max_input_tokens,
        "max_latency_ms": config.max_latency_ms,
        "min_latency_ms": config.min_latency_ms,
        "default_output_tokens": config.default_output_tokens,
        "max_bid_price": config.max_bid_price,
        "min_bid_price": config.min_bid_price,
        "max_retries": config.max_retries,
    }


@router.post("/config/job/reload")
async def reload_job_config_endpoint():
    """
    重新加载 Job 配置
    
    POST /internal/v1/config/job/reload
    
    从环境变量重新加载配置
    """
    from ..services.job_config import reload_job_config
    
    config = reload_job_config()
    return {
        "status": "reloaded",
        "config": {
            "max_output_tokens": config.max_output_tokens,
            "max_input_tokens": config.max_input_tokens,
            "max_latency_ms": config.max_latency_ms,
            "min_latency_ms": config.min_latency_ms,
            "default_output_tokens": config.default_output_tokens,
            "max_bid_price": config.max_bid_price,
            "min_bid_price": config.min_bid_price,
            "max_retries": config.max_retries,
        }
    }





@router.get("/runtimes")
async def get_runtimes():
    """
    获取支持的运行时列表
    GET /internal/v1/runtimes
    Node Agent 可以调用此接口获取运行时配置
    """
    import yaml
    try:
        with open("config/models.yaml", "r") as f:
            config = yaml.safe_load(f)
        runtimes = config.get("runtimes", {})
        return {"runtimes": runtimes, "default": "ollama"}
    except Exception:
        return {
            "runtimes": {
                "ollama": {"endpoint": "http://localhost:11434", "timeout": 60, "api_format": "ollama"},
                "vllm": {"endpoint": "http://localhost:8000/v1", "timeout": 60, "api_format": "openai"},
            },
            "default": "ollama",
        }


@router.get("/nodes/orphans")
async def get_orphan_nodes():
    """
    获取孤儿节点（节点有user_id但用户node_ids中没有该节点）
    GET /internal/v1/nodes/orphans
    """
    from ..database import SessionLocal
    from ..repositories import NodeRepository, UserRepository
    from ..models.db_models import NodeDB
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


# ===== 请求/响应模型 =====

class ResultSubmitRequest(BaseModel):
    """结果提交请求"""
    match_id: str
    result: str = Field(..., description="Base64 编码的推理结果")
    result_hash: str = Field(..., description="结果 SHA256 哈希")
    actual_latency_ms: int = Field(..., ge=0, description="实际延迟（ms）")
    actual_output_tokens: int = Field(..., ge=0, description="实际输出 token 数")


class VerificationResponse(BaseModel):
    """验证响应"""
    verified: bool
    layer: int = Field(..., description="验证层级 (1 或 2)")
    failure_reason: Optional[str] = None
    penalty_applied: Optional[str] = None
    retried: Optional[bool] = Field(None, description="是否已重试")
    similarity: Optional[float] = None


class SettlementRequest(BaseModel):
    """结算请求"""
    match_id: str
    locked_price: float
    actual_tokens: int


class SettlementResponse(BaseModel):
    """结算响应"""
    success: bool
    escrow_id: str
    node_earn: float
    platform_fee: float
    refund_amount: float


class Layer2TriggerRequest(BaseModel):
    """Layer 2 触发请求"""
    match_id: str
    original_result: str


class Layer2SubmitRequest(BaseModel):
    """Layer 2 结果提交"""
    layer2_job_id: str
    second_result: str


# ===== 辅助函数 =====

def _safe_status(status) -> str:
    """安全获取状态值"""
    if hasattr(status, 'value'):
        return status.value
    return str(status)


# ===== 撮合接口 =====

@router.post("/match/trigger")
async def trigger_match_endpoint(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    触发撮合（内部接口）
    Job 提交时自动调用
    """
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 从数据库恢复 Job 对象（简化）
    from ..models import Job
    job = Job(
        model=db_job.model,
        input_tokens=db_job.input_tokens,
        output_tokens_limit=db_job.output_tokens_limit,
        max_latency=db_job.max_latency,
        bid_price=db_job.bid_price,
    )
    job.job_id = db_job.job_id
    job.status = JobStatus(db_job.status.value)
    
    # 添加到撮合队列
    matching_service.add_job(job)
    
    # 触发撮合
    match = matching_service.trigger_match(job_id)
    
    if match:
        # 更新数据库
        job_repo.update(job_id, status=JobStatus.MATCHED)
        
        # 创建 Match 记录
        match_repo = MatchRepository(db)
        db_match = match_repo.create(match)
        
        # 更新 Escrow
        escrow_repo = EscrowRepository(db)
        db_escrow = escrow_repo.get_by_job(job_id)
        if db_escrow:
            db_escrow.match_id = match.match_id
            db.commit()
        
        return {
            "matched": True,
            "match_id": match.match_id,
            "node_id": match.node_id,
            "locked_price": match.locked_price,
        }
    
    return {"matched": False, "message": "No available nodes"}


@router.post("/match/poll")
async def poll_match_endpoint(
    node_id: str,
    db: Session = Depends(get_db)
):
    """
    节点拉取 Job（内部接口）
    返回匹配的 Job 信息
    """
    match = matching_service.poll_node(node_id)
    
    if match:
        # 获取 Job 详情
        job_repo = JobRepository(db)
        db_job = job_repo.get(match.job_id)
        
        if db_job:
            return {
                "has_job": True,
                "match_id": match.match_id,
                "job": {
                    "job_id": match.job_id,
                    "model": db_job.model,
                    "input_tokens": db_job.input_tokens,
                    "output_tokens_limit": db_job.output_tokens_limit,
                    "max_latency": db_job.max_latency,
                    "locked_price": match.locked_price,
                }
            }
    
    return {"has_job": False}


# ===== 验证接口 =====

@router.post("/verify", response_model=VerificationResponse)
async def verify_result_endpoint(
    request: ResultSubmitRequest,
    db: Session = Depends(get_db)
):
    """
    验证执行结果（Layer 1 + 触发 Layer 2）
    
    流程:
    1. Layer 1 基础验证（100%）
    2. 10% 概率触发 Layer 2
    3. 返回验证结果
    """
    # 获取 Match 和 Job
    match_repo = MatchRepository(db)
    db_match = match_repo.get(request.match_id)
    
    if not db_match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    job_repo = JobRepository(db)
    db_job = job_repo.get(db_match.job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 恢复对象
    from ..models import Job, Match
    job = Job(
        model=db_job.model,
        input_tokens=db_job.input_tokens,
        output_tokens_limit=db_job.output_tokens_limit,
        max_latency=db_job.max_latency,
        bid_price=db_job.bid_price,
    )
    job.job_id = db_job.job_id
    job.status = JobStatus(db_job.status.value)
    
    match = Match(
        job_id=db_match.job_id,
        node_id=db_match.node_id,
        locked_price=db_match.locked_price,
    )
    match.match_id = db_match.match_id
    
    # Layer 1 验证
    layer1_passed, failure_reason = verification_service.verify_layer1(
        match=match,
        job=job,
        result=request.result,
        result_hash=request.result_hash,
        actual_latency_ms=request.actual_latency_ms,
        actual_output_tokens=request.actual_output_tokens,
    )
    
    if not layer1_passed:
        # Layer 1 失败 → 触发重试
        retry_result = retry_service.handle_failure(
            match=match,
            job=job,
            failure_type=FailureType.VERIFICATION_FAILED,
            reason=failure_reason,
        )
        
        # 更新数据库中的 Job 状态
        if retry_result:
            # 有重试，更新原 Job 为 failed
            job_repo.update(job.job_id, status=JobStatus.FAILED)
        else:
            # 无重试（已达上限），更新为 failed
            job_repo.update(job.job_id, status=JobStatus.FAILED)
        
        return VerificationResponse(
            verified=False,
            layer=1,
            failure_reason=failure_reason,
            retried=retry_result is not None,
        )
    
    # Layer 1 通过，检查延迟
    is_failed, is_mild = verification_service.check_latency_penalty(
        job=job,
        actual_latency_ms=request.actual_latency_ms,
    )
    
    penalty_applied = None
    if is_failed and is_mild:
        penalty_applied = "mild_latency_penalty"  # 降价结算
    
    # 更新 Match
    db_match.result_hash = request.result_hash
    db_match.actual_latency_ms = request.actual_latency_ms
    db_match.verified = True
    db.commit()
    
    # 检查是否触发 Layer 2
    layer2_triggered = verification_service.should_trigger_layer2()
    
    if layer2_triggered:
        layer2_job_id = verification_service.trigger_layer2(
            match_id=request.match_id,
            job=job,
            original_result=request.result,
        )
        return VerificationResponse(
            verified=True,
            layer=1,
            penalty_applied=penalty_applied,
            layer2_triggered=True,
            layer2_job_id=layer2_job_id,
        )
    
    return VerificationResponse(
        verified=True,
        layer=1,
        penalty_applied=penalty_applied,
    )


@router.post("/verify/layer2")
async def submit_layer2_result_endpoint(
    request: Layer2SubmitRequest,
    db: Session = Depends(get_db)
):
    """
    Layer 2 双跑结果提交
    
    1. 计算相似度
    2. 判定一致性
    3. 记录违规或重置
    """
    try:
        similarity, verdict = verification_service.submit_layer2_result(
            layer2_job_id=request.layer2_job_id,
            second_result=request.second_result,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    # 获取原始 match_id
    layer2_data = verification_service._layer2_jobs.get(request.layer2_job_id)
    if not layer2_data:
        raise HTTPException(status_code=404, detail="Layer2 job not found")
    
    match_id = layer2_data["original_match_id"]
    
    # 获取 Match 和 Node
    match_repo = MatchRepository(db)
    db_match = match_repo.get(match_id)
    
    if not db_match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    # 更新 Match
    db_match.layer2_consistency = similarity
    db_match.verification_layer = 2
    db.commit()
    
    response = {
        "match_id": match_id,
        "similarity": similarity,
        "verdict": verdict,
        "node_id": db_match.node_id,
    }
    
    # 处理不一致情况
    if verdict == "inconsistent":
        should_lock, count = verification_service.record_violation(db_match.node_id)
        
        response["violation_count"] = count
        response["node_locked"] = should_lock
        
        if should_lock:
            # 触发 Stake 冻结（争议）
            stake_service.freeze_stake(
                node_id=db_match.node_id,
                reason=f"Layer2 inconsistency: similarity={similarity}",
                match_ids=[match_id],
            )
            response["dispute_created"] = True
    else:
        # 正常完成，重置违规计数
        verification_service.reset_violations(db_match.node_id)
    
    return response


# ===== 结算接口 =====
import logging
logger = logging.getLogger(__name__)

@router.post("/settlement/execute", response_model=SettlementResponse)
async def execute_settlement_endpoint(
    request: SettlementRequest,
    db: Session = Depends(get_db)
):
    """
    执行结算
    
    分配:
    - Node: 95%
    - Platform: 5%
    - 余额: 退还 Buyer
    """
    # 获取 Escrow
    escrow_repo = EscrowRepository(db)
    db_escrow = escrow_repo.get_by_match(request.match_id)
    
    # 如果没找到，尝试按 match_id 直接查找
    if not db_escrow:
        from ..models.db_models import EscrowDB as EscrowDBModel
        db_escrow = db.query(EscrowDBModel).filter(
            EscrowDBModel.match_id == request.match_id
        ).first()
    
    # 如果还没找到，尝试从 Match 获取 job_id 再查找
    if not db_escrow:
        match_repo = MatchRepository(db)
        db_match_lookup = match_repo.get(request.match_id)
        if db_match_lookup:
            db_escrow = escrow_repo.get_by_job(db_match_lookup.job_id)
    
    # 如果 Escrow 仍然找不到，尝试创建一个新的（备用）
    if not db_escrow:
        # 查找 Match 获取 job_id
        match_repo = MatchRepository(db)
        db_match_for_escrow = match_repo.get(request.match_id)
        if db_match_for_escrow:
            # 创建新的 Escrow
            from ..models.db_models import EscrowDB as EscrowDBModel
            job_repo = JobRepository(db)
            db_job_for_escrow = job_repo.get(db_match_for_escrow.job_id)
            if db_job_for_escrow:
                locked_amount = escrow_service._calculate_escrow(
                    request.locked_price,
                    db_job_for_escrow.input_tokens,
                    db_job_for_escrow.output_tokens_limit
                )
                db_escrow = EscrowDBModel(
                    escrow_id=f"escrow_{db_match_for_escrow.job_id}",
                    job_id=db_match_for_escrow.job_id,
                    match_id=request.match_id,
                    locked_amount=locked_amount,
                    status=EscrowStatusDB.LOCKED,
                )
                db.add(db_escrow)
                db.commit()
                db.refresh(db_escrow)
    
    if not db_escrow:
        raise HTTPException(status_code=404, detail="Escrow not found for match_id: " + request.match_id)
    
    # 计算结算
    actual_cost = escrow_service._calculate_cost(
        request.locked_price,
        request.actual_tokens
    )
    
    # 检查是否有延迟处罚
    match_repo = MatchRepository(db)
    db_match = match_repo.get(request.match_id)
    is_mild_penalty = False
    
    if db_match and db_match.actual_latency_ms:
        job_repo = JobRepository(db)
        db_job = job_repo.get(db_match.job_id)
        if db_job:
            _, is_mild = verification_service.check_latency_penalty(
                job=Job(
                    model=db_job.model,
                    input_tokens=db_job.input_tokens,
                    output_tokens_limit=db_job.output_tokens_limit,
                    max_latency=db_job.max_latency,
                    bid_price=db_job.bid_price,
                ),
                actual_latency_ms=db_match.actual_latency_ms,
            )
            is_mild_penalty = is_mild
    
    # 应用降价（如果有）
    if is_mild_penalty:
        actual_cost *= settlement_config.latency_threshold_mild / 1000 if settlement_config.latency_threshold_mild > 100 else settlement_config.latency_threshold_mild / 1000
    
    # 计算分配
    platform_fee = actual_cost * settlement_config.platform_fee_rate
    node_earn = actual_cost * settlement_config.node_earn_rate
    refund_amount = db_escrow.locked_amount - actual_cost
    
    # 更新 Escrow
    db_escrow.spent_amount = actual_cost
    db_escrow.actual_cost = actual_cost
    db_escrow.actual_tokens = request.actual_tokens
    db_escrow.platform_fee = platform_fee
    db_escrow.node_earn = node_earn
    db_escrow.refund_amount = max(0, refund_amount)
    db_escrow.status = EscrowStatusDB.SETTLED
    db_escrow.settled_at = datetime.utcnow()
    
    # 更新 Match
    if db_match:
        db_match.settled = True
        db_match.settled_at = datetime.utcnow()
    
    # 更新 Job
    if db_match:
        job_repo = JobRepository(db)
        job_repo.update(db_match.job_id, 
                       status=JobStatus.COMPLETED,
                       actual_output_tokens=request.actual_tokens,
                       final_price=actual_cost)
    
    # 释放节点
    if db_match:
        matching_service.release_node(db_match.node_id)
    
    db.commit()
    
    # ===== 双账本同步：链上记录结算 =====
    try:
        from ..services.chain_sync import chain_sync_service
        
        # 获取哈希（从 Match 或生成）
        input_hash = db_match.result_hash if db_match and db_match.result_hash else f"input_{db_match.job_id if db_match else request.match_id}"
        result_hash = request.result_hash if hasattr(request, 'result_hash') else f"result_{request.match_id}"
        
        # 同步到链上
        chain_sync_service.sync_settlement(
            job_id=db_match.job_id if db_match else db_escrow.job_id,
            match_id=request.match_id,
            actual_cost=actual_cost,
            node_earn=node_earn,
            platform_fee=platform_fee,
            refund_amount=max(0, refund_amount),
            input_hash=input_hash,
            result_hash=result_hash,
            actual_tokens=request.actual_tokens
        )
        logger.info(f"Chain sync completed for match {request.match_id[:8]}")
    except Exception as e:
        # 链上同步失败不影响结算（双账本容错）
        logger.error(f"Chain sync failed (non-fatal): {e}")
    
    return SettlementResponse(
        success=True,
        escrow_id=db_escrow.escrow_id,
        node_earn=node_earn,
        platform_fee=platform_fee,
        refund_amount=max(0, refund_amount),
    )


# ===== 重试接口 =====

@router.post("/retry/handle")
async def handle_retry_endpoint(
    match_id: str,
    failure_type: str,
    reason: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    处理失败并触发重试（内部接口）
    """
    match_repo = MatchRepository(db)
    db_match = match_repo.get(match_id)
    
    if not db_match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    job_repo = JobRepository(db)
    db_job = job_repo.get(db_match.job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # 恢复对象
    from ..models import Job, Match
    job = Job(
        model=db_job.model,
        input_tokens=db_job.input_tokens,
        output_tokens_limit=db_job.output_tokens_limit,
        max_latency=db_job.max_latency,
        bid_price=db_job.bid_price,
    )
    job.job_id = db_job.job_id
    job.retry_count = db_job.retry_count
    job.status = JobStatus(db_job.status.value)
    
    match = Match(
        job_id=db_match.job_id,
        node_id=db_match.node_id,
        locked_price=db_match.locked_price,
    )
    match.match_id = db_match.match_id
    
    # 处理失败
    failure_enum = retry_service.FailureType(failure_type)
    new_job = retry_service.handle_failure(
        match=match,
        job=job,
        failure_type=failure_enum,
        reason=reason or "",
    )
    
    if new_job:
        # 更新原 Job 状态
        job_repo.update(db_job.job_id, status=JobStatus.FAILED)
        
        # 尝试撮合
        new_match = matching_service.trigger_match(new_job.job_id)
        
        if new_match:
            return {
                "retried": True,
                "new_match_id": new_match.match_id,
                "new_node_id": new_match.node_id,
                "retry_count": new_job.retry_count,
            }
        
        return {
            "retried": True,
            "queued": True,
            "retry_count": new_job.retry_count,
        }
    
    return {
        "retried": False,
        "reason": "max_retries_exceeded",
    }


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
    from ..models.db_models import DisputeDB
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
        raise HTTPException(status_code=404, detail="Dispute not found")
    
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
    from src.models.db_models import JobDB, EscrowDB, MatchDB, NodeDB
    
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
    from ..services.chain_sync import chain_sync_service
    from ..models.db_models import EscrowDB as EscrowDBModel
    
    if job_id:
        # 单条对账
        db_escrow = db.query(EscrowDBModel).filter(
            EscrowDBModel.job_id == job_id
        ).first()
        
        if not db_escrow:
            raise HTTPException(status_code=404, detail="Escrow not found")
        
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
        settled_escrows = db.query(EscrowDBModel).filter(
            EscrowDBModel.status == EscrowStatusDB.SETTLED
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
    from ..services.chain_sync import chain_sync_service
    
    verified, reason = chain_sync_service.verify_settlement(
        job_id, result_hash, actual_cost
    )
    
    return {
        "job_id": job_id,
        "verified": verified,
        "reason": reason,
        "verified_at": datetime.utcnow().isoformat()
    }

# ===== 数据库迁移接口 =====

@router.post("/db/migrate")
async def db_migrate(db: Session = Depends(get_db)):
    """
    数据库迁移：添加新列到现有表
    """
    from sqlalchemy import text
    import logging
    logger = logging.getLogger(__name__)
    
    migrations = [
        ("nodes", "cluster_id", "VARCHAR(50)"),
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

@router.post("/debug/node-login")
async def debug_node_login(
    node_id: str,
    user_id: str,
    db: Session = Depends(get_db)
):
    """调试: 模拟 node_login"""
    from ..repositories import UserRepository, NodeRepository
    import traceback
    
    result = {}
    
    # 1. Check user
    try:
        user_repo = UserRepository(db)
        is_valid, user_db, error_msg = user_repo.validate_user_id(user_id)
        result["user_valid"] = is_valid
        result["user_error"] = error_msg
    except Exception as e:
        result["user_error"] = str(e)
        return {"error": result}
    
    # 2. Check node
    try:
        node_repo = NodeRepository(db)
        db_node = node_repo.get(node_id)
        result["node_found"] = db_node is not None
        if db_node:
            result["node_user_id"] = db_node.user_id
            result["node_cluster_id"] = db_node.cluster_id
            result["node_runtime"] = db_node.runtime
    except Exception as e:
        result["node_error"] = str(e)
        result["node_trace"] = traceback.format_exc()
    
    return result

@router.post("/debug/test-status-store")
async def debug_test_status_store(
    node_id: str,
    db: Session = Depends(get_db)
):
    """测试 NodeStatusStore"""
    from ..services.node_status_store import update_node_status, get_node_info
    import traceback
    import time
    
    result = {"node_id": node_id}
    
    # Test update_node_status
    try:
        live_status = {
            "timestamp": int(time.time() * 1000),
            "status": {"state": "idle", "vram_used_gb": 0, "vram_total_gb": 24},
            "capacity": {"max_concurrency_total": 2, "max_concurrency_available": 2},
            "load": {"active_jobs": 0, "available_token_capacity": 100000},
        }
        update_node_status(node_id, live_status)
        result["update_status"] = "ok"
    except Exception as e:
        result["update_status"] = "error"
        result["update_error"] = str(e)
        result["update_trace"] = traceback.format_exc()
    
    # Test get_node_info
    try:
        info = get_node_info(node_id)
        result["get_info"] = "ok"
        result["node_info"] = info
    except Exception as e:
        result["get_info"] = "error"
        result["get_error"] = str(e)
        result["get_trace"] = traceback.format_exc()
    
    return result
