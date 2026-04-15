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
Internal API - 撮合/验证/结算接口
包含: match, verify, settlement, retry
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import logging

from ...database import get_db
from ...models.db_models import MatchDB, EscrowDB, EscrowStatusDB
from ...models import JobStatus, Job, Match
from ...repositories import JobRepository, MatchRepository, EscrowRepository
from ...services import matching_service, escrow_service, verification_service, retry_service
from ...services.retry import FailureType
from ...services.settlement_config import settlement_config

router = APIRouter(prefix="", tags=["internal/matching"])
logger = logging.getLogger(__name__)


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


class Layer2SubmitRequest(BaseModel):
    """Layer 2 结果提交"""
    layer2_job_id: str
    second_result: str


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
        raise_not_found("job", job_id)
    
    # 从数据库恢复 Job 对象
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
        raise_not_found("match", match_id)
    
    job_repo = JobRepository(db)
    db_job = job_repo.get(db_match.job_id)
    
    if not db_job:
        raise_not_found("job", job_id)
    
    # 恢复对象
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
            job_repo.update(job.job_id, status=JobStatus.FAILED)
        else:
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
        penalty_applied = "mild_latency_penalty"
    
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
    from ...services import stake_service
    
    try:
        similarity, verdict = verification_service.submit_layer2_result(
            layer2_job_id=request.layer2_job_id,
            second_result=request.second_result,
        )
    except ValueError as e:
        raise_bad_request(str(e))
    
    # 获取原始 match_id
    layer2_data = verification_service._layer2_jobs.get(request.layer2_job_id)
    if not layer2_data:
        raise_not_found("layer2_job", request.layer2_job_id)
    
    match_id = layer2_data["original_match_id"]
    
    # 获取 Match 和 Node
    match_repo = MatchRepository(db)
    db_match = match_repo.get(match_id)
    
    if not db_match:
        raise_not_found("match", match_id)
    
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
        db_escrow = db.query(EscrowDB).filter(
            EscrowDB.match_id == request.match_id
        ).first()
    
    # 如果还没找到，尝试从 Match 获取 job_id 再查找
    if not db_escrow:
        match_repo = MatchRepository(db)
        db_match_lookup = match_repo.get(request.match_id)
        if db_match_lookup:
            db_escrow = escrow_repo.get_by_job(db_match_lookup.job_id)
    
    # 如果 Escrow 仍然找不到，尝试创建一个新的
    if not db_escrow:
        match_repo = MatchRepository(db)
        db_match_for_escrow = match_repo.get(request.match_id)
        if db_match_for_escrow:
            job_repo = JobRepository(db)
            db_job_for_escrow = job_repo.get(db_match_for_escrow.job_id)
            if db_job_for_escrow:
                locked_amount = escrow_service._calculate_escrow(
                    request.locked_price,
                    db_job_for_escrow.input_tokens,
                    db_job_for_escrow.output_tokens_limit
                )
                db_escrow = EscrowDB(
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
        raise_not_found("escrow", request.match_id)
    
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
        from ...services.chain_sync import chain_sync_service
        
        # 获取哈希
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
        raise_not_found("match", match_id)
    
    job_repo = JobRepository(db)
    db_job = job_repo.get(db_match.job_id)
    
    if not db_job:
        raise_not_found("job", job_id)
    
    # 恢复对象
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
