"""
Nodes API - F2: 节点注册与状态管理
来源: Function/F2
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
import json
import base64
import uuid
import logging

logger = logging.getLogger(__name__)

from ..database import get_db
from ..models import Node, NodeCreate, NodeResponse, NodeStatus, NodePollResponse, NodeResultSubmit
from ..models.db_models import NodeDB, NodeStatusDB, StakeRecordDB, MatchDB
from ..repositories import NodeRepository, MatchRepository, JobRepository, EscrowRepository
from ..services import matching_service, escrow_service, verification_service, stake_service
from config import settings
from ..services.settlement_config import settlement_config

router = APIRouter(prefix="/nodes", tags=["nodes"])


def _debug_error(e: Exception, context: str = "") -> HTTPException:
    """统一错误处理 (debug 模式返回详细信息)"""
    if settings.debug:
        import traceback
        logger.error(f"{context}: {e}\n{traceback.format_exc()}")
        return HTTPException(status_code=500, detail=f"{context}: {e}")
    else:
        logger.error(f"{context}: {e}")
        return HTTPException(status_code=500, detail="Internal Server Error")


def _safe_status(status) -> str:
    """安全获取状态值"""
    if hasattr(status, 'value'):
        return status.value
    return str(status)


@router.post("", response_model=NodeResponse)
async def register_node(
    node_create: NodeCreate,
    db: Session = Depends(get_db)
):
    """
    Register new node (Required: user_id, runtime and model)
    注册新节点（必填：user_id, runtime 和 model）
    
    Returns required Stake threshold
    返回所需的 Stake 门槛
    """
    # Validate user_id / 验证用户 ID
    user_id = node_create.user_id
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    
    # Validate user exists and is active / 验证用户存在且有效
    from ..repositories import UserRepository
    user_repo = UserRepository(db)
    is_valid, user_db, error_msg = user_repo.validate_user_id(user_id)
    
    if not is_valid:
        logger.warning(f"User validation failed: {error_msg}")
        raise HTTPException(status_code=403, detail=error_msg)
    
    # 1. Create Node Pydantic model with nested structure
    # 创建 Node Pydantic 模型（使用嵌套结构）
    from ..models import Node
    from ..models.node import Pricing
    
    # 从请求中提取 avg_latency_ms（默认100）
    avg_latency_ms = 100
    if node_create.pricing and hasattr(node_create.pricing, 'avg_latency_ms'):
        avg_latency_ms = node_create.pricing.avg_latency_ms or 100
    
    # 直接使用 node_create.pricing 对象（不要转换为 dict）
    # 因为 Pricing 使用 alias，dict 构造会丢失数据
    pricing_obj = node_create.pricing if node_create.pricing else Pricing()
    
    node = Node(
        node_id=str(uuid.uuid4()),
        user_id=user_id,
        runtime=node_create.runtime or {'type': 'ollama', 'loaded_models': []},
        hardware=node_create.hardware or {'gpu_type': 'unknown', 'gpu_count': 1},
        reliability={'avg_latency_ms': avg_latency_ms},
        pricing=pricing_obj,
        location=node_create.location or {'region': 'unknown'},
    )
    node.economy.stake_tier = 'personal'
    node.state.status = 'online'
    
    # 2. 保存到数据库
    node_repo = NodeRepository(db)
    db_node = node_repo.create(node)
    
    # 3. 更新用户的 node_ids（系统自动维护）
    user_repo.add_node_to_user(user_id, node.node_id)
    
    # 4. 注册到撮合引擎（已移除，matching_service 从 NodeStatusStore 读取节点状态）
    
    # 5. 立即上报首次状态（使节点立即在线）
    from ..services.node_status_store import update_node_status
    import time
    current_time_ms = int(time.time() * 1000)
    
    # Live Status（实时状态）
    live_status = {
        "timestamp": current_time_ms,
        "status": {
            "state": "idle",
            "vram_used_gb": 0,
            "vram_total_gb": node.hardware.vram_per_gpu_gb or 80,
        },
        "capacity": {
            "max_concurrency_available": node.capability.max_concurrency_total,
            "max_concurrency_total": node.capability.max_concurrency_total,
        },
        "load": {
            "active_jobs": 0,
            "available_token_capacity": node.capability.max_queue_tokens,
        },
    }
    update_node_status(node.node_id, live_status)
    
    # Capacity Report（容量报告）
    capacity_report = {
        "timestamp": current_time_ms,
        "runtime": node.runtime.model_dump() if hasattr(node.runtime, 'model_dump') else {"type": "ollama", "loaded_models": []},
        "capacity": {
            "max_concurrency_total": node.capability.max_concurrency_total,
            "tokens_per_sec": node.capability.tokens_per_sec,
            "max_queue_tokens": node.capability.max_queue_tokens,
        },
    }
    # Capacity report 也更新到 status store（带不同前缀或覆盖）
    # 更新 runtime 信息到 NodeDB
    node_repo.update(node.node_id, 
        runtime=json.dumps(node.runtime.model_dump()) if hasattr(node.runtime, 'model_dump') else '{}',
        model=node.runtime.loaded_models[0] if node.runtime.loaded_models else 'unknown'
    )
    
    # 6. 响应
    return NodeResponse(
        node_id=node.node_id,
        user_id=user_id,
        status=NodeStatus(_safe_status(db_node.status)),
        stake_required=db_node.stake_required,
        gpu_type=node.hardware.gpu_type,
        gpu_count=node.hardware.gpu_count,
        stake_amount=db_node.stake_amount,
        slot_count=0,  # MVP: no slots
        worker_count=0,  # MVP: no workers
        next_step=f"Deposit {db_node.stake_required} USDC to activate",
    )


@router.get("/{node_id}")
async def get_node(
    node_id: str,
    db: Session = Depends(get_db)
):
    """获取节点信息"""
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return {
        "node_id": db_node.node_id,
        "gpu_type": db_node.gpu_type,
        "vram_gb": db_node.vram_gb,
        "model": db_node.model,  # 从 Node Agent 配置读取
        "model_support": db_node.model_support,
        "ask_price": db_node.ask_price,
        "avg_latency": db_node.avg_latency,
        "region": db_node.region,
        "status": _safe_status(db_node.status),
        "stake_amount": db_node.stake_amount,
        "stake_required": db_node.stake_required,
        "stake_tier": db_node.stake_tier,
        "registered_at": db_node.registered_at.isoformat() if db_node.registered_at else None,
        "last_heartbeat": db_node.last_heartbeat.isoformat() if db_node.last_heartbeat else None,
    }


@router.post("/{node_id}/online")
async def node_online(
    node_id: str,
    db: Session = Depends(get_db)
):
    """节点上线"""
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # MVP 模式: stake_required 为 0 时跳过 stake 检查
    if db_node.stake_required > 0:
        stake_record = db.query(StakeRecordDB).filter(
            StakeRecordDB.node_id == node_id
        ).first()
        
        if not stake_record or stake_record.status != "active":
            raise HTTPException(
                status_code=400,
                detail="Stake not deposited or frozen"
            )
    
    # 更新数据库
    node_repo.update(node_id, status=NodeStatus.ONLINE)
    
    # Register node to matching engine (in-memory service)
    # 注册节点到撮合引擎（内存服务）
    from ..models import Node
    import json
    
    # 解析 runtime JSON
    runtime_data = json.loads(db_node.runtime) if isinstance(db_node.runtime, str) else {'type': 'ollama', 'loaded_models': []}
    model_support = json.loads(db_node.model_support) if isinstance(db_node.model_support, str) else (db_node.model_support or [])
    
    node_model = Node(
        node_id=node_id,
        user_id=db_node.user_id,
        runtime=runtime_data,
        hardware={'gpu_type': db_node.gpu_type, 'gpu_count': db_node.gpu_count},
        reliability={'avg_latency_ms': db_node.avg_latency},
        pricing={'ask_price_usdc_per_mtoken': db_node.ask_price},
        location={'region': db_node.region},
    )
    node_model.state.status = 'online'
    
    return {
        "node_id": node_id,
        "status": NodeStatus.ONLINE.value,
        "message": "Node is now online and available for matching"
    }


@router.post("/{node_id}/offline")
async def node_offline(
    node_id: str,
    db: Session = Depends(get_db)
):
    """节点下线"""
    node_repo = NodeRepository(db)
    node_repo.update(node_id, status=NodeStatus.OFFLINE)
    
    return {
        "node_id": node_id,
        "status": NodeStatus.OFFLINE.value,
        "message": "Node is now offline"
    }


@router.delete("/{node_id}")
async def delete_node(
    node_id: str,
    db: Session = Depends(get_db)
):
    """
    删除节点（系统自动维护 User.node_ids）
    Delete node (system auto-maintains User.node_ids)
    
    只能由节点所属用户调用
    """
    node_repo = NodeRepository(db)
    user_repo = UserRepository(db)
    
    # 获取节点信息
    node = node_repo.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 获取用户 ID
    user_id = node.metadata.get("user_id") if node.metadata else None
    
    # 从用户 node_ids 移除（系统自动维护）
    if user_id:
        user_repo.remove_node_from_user(user_id, node_id)
    
    # NodeStatusStore 会自动清理（TTL过期）
    
    # 删除节点记录
    node_repo.delete(node_id)
    
    return {
        "node_id": node_id,
        "message": "Node deleted successfully"
    }


@router.post("/{node_id}/poll", response_model=NodePollResponse)
async def poll_job(
    node_id: str,
    db: Session = Depends(get_db)
):
    """
    节点拉取 Job
    
    主动触发撮合，为该节点匹配待处理的 Job
    """
    # 检查节点状态
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 更新心跳
    node_repo.update_heartbeat(node_id)
    
    # 检查节点是否在线（基于 10 秒内的 live_status）
    from ..services.node_status_store import node_status_store
    is_recent = node_status_store.is_online(node_id, max_age_seconds=10)
    
    # DB 状态为 ONLINE 且最近有 live_status 报告则视为在线
    if db_node.status != NodeStatusDB.ONLINE and not is_recent:
        return NodePollResponse(has_job=False)
    
    # 触发撮合（内存服务）
    try:
        match = matching_service.poll_node(node_id)
    except Exception as e:
        logger.error(f"poll_node error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    
    if match:
        # 更新 Escrow.match_id (修复关联问题)
        escrow_repo = EscrowRepository(db)
        db_escrow = escrow_repo.get_by_job(match.job_id)
        if db_escrow and not db_escrow.match_id:
            db_escrow.match_id = match.match_id
            db.commit()
        
        # 获取完整 Job 信息
        job_repo = JobRepository(db)
        db_job = job_repo.get(match.job_id)
        
        # 获取 prompt
        prompt = db_job.prompt if db_job and db_job.prompt else "Hello"
        
        # 获取 generation 参数
        max_tokens = db_job.output_tokens_limit if db_job else 100
        
        # 构建完整的 invoke 结构 (OpenAI 兼容)
        model_info = {
            "name": match.model,
            "family": match.model.split(":")[0] if ":" in match.model else match.model,
            "context_window": 32768
        }
        
        invoke_input = {
            "type": "chat_completion",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            "prompt_raw": None
        }
        
        generation = {
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "top_p": 0.9,
            "stream": False
        }
        
        runtime = {
            "backend": "ollama",
            "api_style": "openai"
        }
        
        return NodePollResponse(
            has_job=True,
            execution_id=f"exec_{match.match_id}",
            job_id=match.job_id,
            slot_id=match.slot_id,
            model=match.model,  # Model name string
            model_info=model_info,  # Extended model info
            input=invoke_input,
            generation=generation,
            runtime=runtime,
            locked_price=match.locked_price,
        )
    
    return NodePollResponse(has_job=False)


@router.post("/{node_id}/jobs/{job_id}/result")
async def submit_result(
    node_id: str,
    job_id: str,
    result_submit: NodeResultSubmit,
    db: Session = Depends(get_db)
):
    """
    节点提交执行结果
    
    触发验证流程
    """
    # 获取 Match (先从内存，再从数据库) - TD-001 修复
    match = matching_service.get_match_by_job(job_id)
    
    if not match:
        # 从数据库查找 Match
        db_match = db.query(MatchDB).filter(MatchDB.job_id == job_id).first()
        if db_match:
            # 转换为内存 Match 对象
            from ..models import Match
            match = Match(
                job_id=db_match.job_id,
                node_id=db_match.node_id,
                locked_price=db_match.locked_price,
            )
            match.match_id = db_match.match_id
        else:
            raise HTTPException(status_code=404, detail="Match not found")
    
    # 检查是否是该节点
    if match.node_id != node_id:
        raise HTTPException(status_code=403, detail="Not your job")
    
    # 获取 Job 对象
    from ..models import Job
    job_repo = JobRepository(db)
    db_job = job_repo.get(job_id)
    
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        job = Job(
            user_id=db_job.user_id or "",
            model=db_job.model,
            input_tokens=db_job.input_tokens,
            output_tokens_limit=db_job.output_tokens_limit,
            max_latency=db_job.max_latency,
            bid_price=float(db_job.bid_price),
        )
        job.job_id = db_job.job_id
    except Exception as e:
        raise _debug_error(e, "Job construct error")
    
    # Layer 1 验证
    layer1_passed, _ = verification_service.verify_layer1(
        match=match,
        job=job,
        result=result_submit.result,
        result_hash=result_submit.result_hash,
        actual_latency_ms=result_submit.actual_latency_ms,
        actual_output_tokens=result_submit.actual_tokens,
    )
    
    # 10% 概率触发 Layer 2
    layer2_triggered = verification_service.should_trigger_layer2()
    layer2_job_id = None
    
    if layer2_triggered and layer1_passed:
        layer2_job_id = verification_service.trigger_layer2(
            match_id=match.match_id,
            job=job,
            original_result=result_submit.result,
        )
    
    # 解码并保存结果
    try:
        decoded_result = base64.b64decode(result_submit.result).decode()
    except:
        decoded_result = result_submit.result
    
    job_repo.update(job_id, 
        status="completed",
        result=decoded_result,
        actual_output_tokens=result_submit.actual_tokens,
        actual_latency_ms=result_submit.actual_latency_ms,
        completed_at=datetime.utcnow()
    )
    
    # 自动触发结算
    settlement_result = None
    try:
        escrow_repo = EscrowRepository(db)
        db_escrow = escrow_repo.get_by_job(job_id)
        if db_escrow and db_escrow.status == "locked":
            # 计算实际成本
            actual_cost = escrow_service._calculate_cost(
                match.locked_price,
                result_submit.actual_output_tokens
            )
            
            # 计算分配
            platform_fee = actual_cost * settlement_config.platform_fee_rate
            node_earn = actual_cost * settlement_config.node_earn_rate
            refund_amount = db_escrow.locked_amount - actual_cost
            
            # 更新 Escrow
            db_escrow.spent_amount = actual_cost
            db_escrow.actual_cost = actual_cost
            db_escrow.actual_tokens = result_submit.actual_output_tokens
            db_escrow.platform_fee = platform_fee
            db_escrow.node_earn = node_earn
            db_escrow.refund_amount = refund_amount
            db_escrow.status = "settled"
            db_escrow.settled_at = datetime.utcnow()
            
            # 更新 Job 的 final_price
            job_repo.update(job_id, final_price=actual_cost)
            
            db.commit()
            settlement_result = {"cost": actual_cost, "node_earn": node_earn, "platform_fee": platform_fee}
            logger.info(f"✅ 自动结算完成: job={job_id}, cost={actual_cost}, node_earn={node_earn}")
    except Exception as e:
        logger.error(f"结算失败: {e}")
    
    response = {
        "received": True,
        "verification_triggered": True,
        "layer": 1 if not layer2_triggered else 2,
        "match_id": match.match_id,
        "job_id": job_id,
    }
    
    if layer2_job_id:
        response["layer2_job_id"] = layer2_job_id
    
    # 释放节点（允许节点接收新 Job）
    matching_service.release_node(node_id)
    return response


@router.post("/{node_id}/stake/deposit")
async def deposit_stake(
    node_id: str,
    tx_hash: str = "mock-tx-hash",  # TD-003: 设为可选，默认mock值
    db: Session = Depends(get_db)
):
    """
    确认 Stake 存款
    
    tx_hash: 链上交易哈希 (可选，MVP阶段默认为mock)
    """
    # 获取节点信息
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 检查是否已有存款
    existing = db.query(StakeRecordDB).filter(
        StakeRecordDB.node_id == node_id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Stake already deposited"
        )
    
    # 创建存款记录
    stake_record = StakeRecordDB(
        id=f"stake_{node_id}",
        node_id=node_id,
        amount=db_node.stake_required,
        tx_hash=tx_hash,
        status="active",
    )
    db.add(stake_record)
    
    # 更新节点 stake_amount
    db_node.stake_amount = db_node.stake_required
    
    db.commit()
    
    return {
        "node_id": node_id,
        "stake_amount": stake_record.amount,
        "status": stake_record.status,
        "message": f"Stake of {stake_record.amount} USDC deposited successfully"
    }


@router.get("/{node_id}/status")
async def get_node_status(
    node_id: str,
    db: Session = Depends(get_db)
):
    """获取节点状态和统计"""
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        return {
            "node_id": node_id,
            "status": "not_registered",
            "is_frozen": False,
            "violations": 0,
        }
    
    # 检查是否冻结
    is_frozen = stake_service.is_node_frozen(node_id)
    
    # 获取违规次数
    violations = verification_service.get_node_violations(node_id)
    
    # 获取匹配统计
    match_count = db.query(MatchDB).filter(MatchDB.node_id == node_id).count()
    
    return {
        "node_id": node_id,
        "status": _safe_status(db_node.status),
        "is_frozen": is_frozen,
        "violations": violations,
        "total_matches": match_count,
        "stake_amount": db_node.stake_amount,
        "stake_required": db_node.stake_required,
    }


@router.get("")
async def list_nodes(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """列出节点列表"""
    nodes = db.query(NodeDB).offset(offset).limit(limit).all()
    
    return {
        "items": [
            {
                "node_id": node.node_id,
                "gpu_type": node.gpu_type,
                "vram_gb": node.vram_gb,
                "ask_price": node.ask_price,
                "status": _safe_status(node.status),
                "region": node.region,
                "model": node.model,  # 从 Node Agent 配置读取
            }
            for node in nodes
        ],
        "total": db.query(NodeDB).count(),
        "limit": limit,
        "offset": offset,
    }


@router.post("/{node_id}/heartbeat")
async def node_heartbeat(
    node_id: str,
    heartbeat_data: dict,
    db: Session = Depends(get_db)
):
    """
    节点心跳（HTTP Polling 模式）
    
    Node Agent 定期发送心跳，报告状态
    包含用户身份验证
    
    DCM v3.2 重要更新:
    - 心跳中可以包含 runtime 和 model
    - 用于更新 Node 的运行时信息
    - Node Agent 启动 Runtime 后会通过心跳更新
    """
    # Validate user_id from heartbeat / 验证心跳中的用户 ID
    user_id = heartbeat_data.get("user_id")
    user_disabled = False
    
    if user_id:
        from ..repositories import UserRepository
        user_repo = UserRepository(db)
        is_valid, user_db, error_msg = user_repo.validate_user_id(user_id)
        
        if not is_valid:
            logger.warning(f"User validation failed on heartbeat: {error_msg}")
            # Return 403 to indicate user is disabled/invalid
            raise HTTPException(status_code=403, detail=error_msg)
        
        # Check if user is disabled
        if user_db.status == "disabled":
            user_disabled = True
            logger.warning(f"User {user_id} is disabled!")
    
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 更新心跳时间 / Update heartbeat time
    node_repo.update_heartbeat(node_id)
    
    # ===== 更新 Runtime 和 Model (DCM v3.2) =====
    # Node Agent 启动 Runtime 后会通过心跳更新这些字段
    update_fields = {}
    
    # runtime 和 model 可以在心跳中更新
    if heartbeat_data.get("runtime"):
        update_fields["runtime"] = heartbeat_data["runtime"]
    
    if heartbeat_data.get("model"):
        update_fields["model"] = heartbeat_data["model"]
    
    # GPU 信息也可能通过心跳更新
    if heartbeat_data.get("gpu_type"):
        update_fields["gpu_type"] = heartbeat_data["gpu_type"]
    
    if heartbeat_data.get("vram_gb"):
        update_fields["vram_gb"] = heartbeat_data["vram_gb"]
    
    if update_fields:
        node_repo.update(node_id, **update_fields)
        logger.info(f"Node {node_id} updated via heartbeat: {list(update_fields.keys())}")
    
    # 检查节点是否在 NodeStatusStore 中（无需手动注册）
    from ..services.node_status_store import node_status_store
    is_online = node_status_store.is_online(node_id, max_age_seconds=10)
    re_register = not is_online and db_node.status == NodeStatusDB.ONLINE
    
    # 获取 Pre-lock Jobs (通过 matching_service)
    pre_lock_jobs = []
    try:
        # 通过内存服务获取 Pre-lock Jobs
        prelocked_jobs = matching_service.get_node_prelock_jobs(node_id)
        
        for job in prelocked_jobs:
            pre_lock_jobs.append({
                "job_id": job.job_id,
                "prompt": job.prompt,
                "model": job.model,
                "pre_lock_expires_at": job.pre_lock_expires_at.isoformat() if job.pre_lock_expires_at else None,
            })
        
        if pre_lock_jobs:
            logger.info(f"节点 {node_id} 有 {len(pre_lock_jobs)} 个 Pre-lock Jobs")
    except Exception as e:
        logger.warning(f"获取 Pre-lock Jobs 失败: {e}")
    
    return {
        "node_id": node_id,
        "status": heartbeat_data.get("status", "idle"),
        "timestamp": int(datetime.utcnow().timestamp() * 1000),
        "is_online": is_online,
        "re_register": re_register,
        "pre_lock_jobs": pre_lock_jobs,
        "pre_lock_count": len(pre_lock_jobs),
        # User authentication status / 用户认证状态
        "user_disabled": user_disabled,
        "user_id": user_id,
    }


@router.post("/{node_id}/live_status")
async def node_live_status(
    node_id: str,
    status_data: dict,
    db: Session = Depends(get_db)
):
    """
    节点实时状态上报 (Node Live Status Report)
    
    频率: 2-5 秒
    用途: 实时调度决策
    
    DCM v3.2:
    - Node Agent 发送实时状态到 Match Engine
    - Match Engine 使用此数据做调度决策
    """
    from ..services.node_status_store import update_node_status
    
    # 验证 Node 存在
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 更新到 NodeStatusStore
    update_node_status(node_id, status_data)
    
    logger.debug(f"Node {node_id} live status updated: concurrency={status_data.get('capacity', {}).get('max_concurrency_available', 0)}")
    
    return {
        "received": True,
        "node_id": node_id,
        "timestamp": status_data.get("timestamp"),
    }


@router.post("/{node_id}/capacity_report")
async def node_capacity_report(
    node_id: str,
    report_data: dict,
    db: Session = Depends(get_db)
):
    """
    节点容量报告 (Node Capacity Report)
    
    频率: 30-60 秒
    用途: 稳态信息更新
    
    DCM v3.2:
    - 更新 Node 的 runtime、models、capability
    - 可能触发 Cluster ID 重新计算
    - 返回新的 cluster_id（如果有变化）
    """
    from ..services.node_status_store import update_node_status
    
    # 验证 Node 存在
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 更新 runtime 和 model（如果提供）
    update_fields = {}
    
    if report_data.get("runtime"):
        runtime = report_data["runtime"]
        update_fields["runtime"] = runtime.get("type", "ollama")
        update_fields["model"] = ",".join(runtime.get("loaded_models", []))
    
    if report_data.get("capacity"):
        cap = report_data["capacity"]
        if cap.get("max_concurrency_total"):
            update_fields["max_concurrency"] = cap["max_concurrency_total"]
    
    if update_fields:
        node_repo.update(node_id, **update_fields)
    
    # 更新到 NodeStatusStore（包含 capacity info）
    update_node_status(node_id, report_data)
    
    # 检查 Cluster ID 变化（通过 Match Engine）
    new_cluster_id = None
    try:
        # 获取新的 cluster_id
        from ..services.cluster_builder import build_cluster_id
        
        models = report_data.get("runtime", {}).get("loaded_models", [])
        if models:
            # 使用第一個模型作为代表
            primary_model = models[0]
            
            new_cluster_id = build_cluster_id(
                region=db_node.region,
                stake_tier="personal",  # TODO: 从 Node 的 stake_tier 获取
                models=models,
                quality_score=0.9,  # TODO: 从历史数据获取
                success_rate=0.95,  # TODO: 从历史数据获取
            )
            
            if db_node.cluster_id != new_cluster_id:
                node_repo.update(node_id, cluster_id=new_cluster_id)
                logger.info(f"Node {node_id} cluster updated: {db_node.cluster_id} -> {new_cluster_id}")
    except Exception as e:
        logger.error(f"Failed to update cluster_id: {e}")
    
    return {
        "received": True,
        "node_id": node_id,
        "timestamp": report_data.get("timestamp"),
        "new_cluster_id": new_cluster_id,
    }


@router.post("/{node_id}/jobs/{job_id}/error")
async def report_job_error(
    node_id: str,
    job_id: str,
    error_data: dict,
    db: Session = Depends(get_db)
):
    """
    节点报告 Job 执行错误
    """
    match_repo = MatchRepository(db)
    db_match = match_repo.get_by_job(job_id)
    
    if not db_match or db_match.node_id != node_id:
        raise HTTPException(status_code=404, detail="Match not found")
    
    error_type = error_data.get("error_type", "unknown")
    error_message = error_data.get("error_message", "")
    
    # 更新 Match 记录
    match_repo.update(db_match.match_id, error_message=error_message)
    
    return {
        "received": True,
        "job_id": job_id,
        "error_type": error_type,
    }


@router.get("/{node_id}/config")
async def get_node_config(
    node_id: str,
    db: Session = Depends(get_db)
):
    """
    获取节点配置信息（用于 Node Agent 初始化）
    """
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return {
        "node_id": db_node.node_id,
        "model": db_node.model_support,  # 动态获取
        "ask_price": db_node.ask_price,
        "avg_latency": db_node.avg_latency,
        "heartbeat_interval": 30,
        "max_concurrent_jobs": 1,  # MVP 固定
    }
