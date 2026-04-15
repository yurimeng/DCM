"""
Nodes API - F2: 节点注册与状态管理
来源: Function/F2
"""

from fastapi import APIRouter, HTTPException, Depends, Body
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
    import traceback
    logger.error(f"{context}: {e}\n{traceback.format_exc()}")
    return HTTPException(status_code=500, detail=f"{context}: {e}")


def _safe_status(status) -> str:
    """安全获取状态值"""
    if hasattr(status, 'value'):
        return status.value
    return str(status)


@router.post("")
async def register_node(
    body: dict = Body(...),
    db: Session = Depends(get_db)
):
    """
    Register new node
    
    Input: {
        user_id: str,
        runtime: {type, loaded_models},
        hardware: {gpu_type, gpu_count},
        location: {region},
        pricing: {ask_price}
    }
    
    Output: {status: "OK", node_id: "xxx"} or {status: "Failed", error: "..."}
    
    Note: cluster_id will be assigned after capacity_update
    """
    import uuid
    import json
    
    # 1. Get user_id
    user_id = body.get("user_id")
    if not user_id:
        return {"status": "Failed", "error": "user_id required"}
    
    # 2. Validate user
    from ..repositories import UserRepository
    user_repo = UserRepository(db)
    is_valid, _, error_msg = user_repo.validate_user_id(user_id)
    if not is_valid:
        return {"status": "Failed", "error": error_msg or "Invalid user"}
    
    # 3. Create Node
    from ..models import Node
    from ..models.node import Pricing
    
    runtime = body.get("runtime", {"type": "ollama", "loaded_models": []})
    hardware = body.get("hardware", {"gpu_type": "unknown", "gpu_count": 1})
    location = body.get("location", {"region": "unknown"})
    pricing_data = body.get("pricing", {})
    
    node = Node(
        node_id=str(uuid.uuid4()),
        user_id=user_id,
        runtime=runtime,
        hardware=hardware,
        pricing=Pricing(),
        location=location,
    )
    node.economy.stake_tier = 'personal'
    node.state.status = 'online'
    
    # 4. Save to DB
    from ..repositories import NodeRepository
    node_repo = NodeRepository(db)
    try:
        db_node = node_repo.create(node)
    except Exception as e:
        return {"status": "Failed", "error": str(e)}
    
    # 5. Update user's node_ids
    user_repo.add_node_to_user(user_id, node.node_id)
    
    # 6. Update runtime info
    node_repo.update(node.node_id, 
        runtime=json.dumps(runtime),
        model=runtime.get("loaded_models", [None])[0] if runtime.get("loaded_models") else "unknown"
    )
    
    return {"status": "OK", "node_id": node.node_id}
    return NodeResponse(
        node_id=node.node_id,
        user_id=user_id,
        status=NodeStatus(_safe_status(db_node.status)),
        stake_required=db_node.stake_required,
        gpu_type=node.hardware.gpu_type,
        gpu_count=node.hardware.gpu_count,
        stake_amount=db_node.stake_amount,
        slot_count=0,
        worker_count=0,
        next_step=f"Deposit {db_node.stake_required} USDC to activate",
        cluster_id=cluster_id,  # 返回 cluster_id 给 Node
    )


@router.post("/{node_id}/login")
async def node_login(
    node_id: str,
    db: Session = Depends(get_db)
):
    """Node Login - Verify node exists"""
    from ..repositories import NodeRepository
    
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        return {"status": "Failed", "error": "Node not found"}
    
    return {"status": "OK"}


@router.get("/debug/matching-status")
async def debug_matching_status(db: Session = Depends(get_db)):
    """
    调试端点：检查匹配系统状态
    """
    from ..services.node_status_store import (
        list_online_nodes, list_nodes, node_status_store
    )
    from ..repositories import NodeRepository, JobRepository
    
    # DB nodes
    node_repo = NodeRepository(db)
    all_db_nodes = node_repo.list_all()
    
    # NodeStatusStore nodes
    all_store_nodes = list_nodes()
    online_store_nodes = list_online_nodes()
    
    # Pending jobs
    job_repo = JobRepository(db)
    pending_jobs = job_repo.list_by_status(status=None)  # Get all
    pending = [j for j in pending_jobs if j.status.value == "pending"]
    
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
            "total": len(pending),
            "jobs": [
                {
                    "job_id": j.job_id[:20],
                    "model": j.model,
                    "bid_price": j.bid_price,
                }
                for j in pending
            ]
        },
        "backend_type": type(node_status_store._backend).__name__,
    }


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
    
    # 检查节点是否在线（使用新的 list_nodes API）
    from ..services.node_status_store import get_node_info
    node_info = get_node_info(node_id)
    
    # DB 状态为 ONLINE 且节点在 NodeStatusStore 中在线才处理
    if db_node.status != NodeStatusDB.ONLINE and not node_info.is_online:
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
                result_submit.actual_tokens
            )
            
            # 计算分配
            platform_fee = actual_cost * settlement_config.platform_fee_rate
            node_earn = actual_cost * settlement_config.node_earn_rate
            refund_amount = db_escrow.locked_amount - actual_cost
            
            # 更新 Escrow
            db_escrow.spent_amount = actual_cost
            db_escrow.actual_cost = actual_cost
            db_escrow.actual_tokens = result_submit.actual_tokens
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
    
    注意: cluster_id 由 capacity_report 生成，不在这里处理
    """
    from ..services.node_status_store import update_node_status
    
    # 验证 Node 存在
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 更新到 NodeStatusStore（不生成 cluster_id）
    update_node_status(node_id, status_data)
    
    logger.debug(f"Node {node_id} live status updated")
    
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
    from ..services.node_status_store import update_node_status, node_status_store
    
    # 验证 Node 存在
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # ===== 提取静态配置并更新 DB =====
    update_fields = {}
    
    # 1. runtime 和 models
    if report_data.get("runtime"):
        runtime = report_data["runtime"]
        update_fields["runtime"] = json.dumps(runtime)
        if runtime.get("loaded_models"):
            update_fields["model"] = runtime["loaded_models"][0]
            update_fields["model_support"] = json.dumps(runtime["loaded_models"])
    
    # 2. ask_price
    if report_data.get("ask_price"):
        update_fields["ask_price"] = float(report_data["ask_price"])
    
    # 3. avg_latency
    if report_data.get("avg_latency"):
        update_fields["avg_latency"] = int(report_data["avg_latency"])
    
    # 4. gpu_count
    if report_data.get("gpu_count"):
        update_fields["gpu_count"] = int(report_data["gpu_count"])
    
    # 5. capacity
    if report_data.get("capacity"):
        cap = report_data["capacity"]
        if cap.get("max_concurrency_total"):
            update_fields["max_concurrency"] = cap["max_concurrency_total"]
    
    if update_fields:
        node_repo.update(node_id, **update_fields)
        logger.info(f"Node {node_id} static config updated: {update_fields}")
    
    # ===== 合并状态到 NodeStatusStore =====
    # 获取之前的状态
    prev_status = node_status_store.get(node_id)
    
    # 合并状态：capacity_report 优先使用自己的数据
    merged_status = {
        "timestamp": report_data.get("timestamp"),
        "status": {
            "status": "online",
        },
        "capacity": report_data.get("capacity", {}),
        "load": report_data.get("load", {}),
    }
    
    # 从 report_data 提取静态配置
    runtime_data = report_data.get("runtime", {})
    report_models = runtime_data.get("loaded_models", [])
    
    # model_support: 优先使用 runtime.loaded_models
    if report_models:
        merged_status["status"]["model_support"] = report_models
    elif prev_status:
        merged_status["status"]["model_support"] = prev_status.get("status", {}).get("model_support", [])
    
    # ask_price
    if report_data.get("ask_price"):
        merged_status["status"]["ask_price"] = float(report_data["ask_price"])
    elif prev_status:
        merged_status["status"]["ask_price"] = prev_status.get("status", {}).get("ask_price", 0.001)
    
    # avg_latency
    if report_data.get("avg_latency"):
        merged_status["status"]["avg_latency"] = int(report_data["avg_latency"])
    elif prev_status:
        merged_status["status"]["avg_latency"] = prev_status.get("status", {}).get("avg_latency", 100)
    
    # gpu_count
    if report_data.get("gpu_count"):
        merged_status["status"]["gpu_count"] = int(report_data["gpu_count"])
    elif prev_status:
        merged_status["status"]["gpu_count"] = prev_status.get("status", {}).get("gpu_count", 1)
    
    # 从 prev_status 保留其他字段
    if prev_status:
        prev_st = prev_status.get("status", {})
        merged_status["status"].setdefault("gpu_type", prev_st.get("gpu_type", ""))
        merged_status["status"].setdefault("vram_used_gb", prev_st.get("vram_used_gb", 0))
        merged_status["status"].setdefault("vram_total_gb", prev_st.get("vram_total_gb", 0))
        if not report_data.get("load"):
            merged_status["load"] = prev_status.get("load", {})
    
    # ===== 准备 capacity_info 用于生成 cluster_id =====
    models = merged_status["status"].get("model_support", [])
    if report_data.get("runtime"):
        models = report_data["runtime"].get("loaded_models", [])
    if not models and prev_status:
        models = prev_status.get("status", {}).get("model_support", [])
    
    capacity_info = {
        "runtime": {"type": report_data.get("runtime", {}).get("type", "ollama"), "loaded_models": models},
        "region": db_node.region or "unknown",
        "stake_tier": db_node.stake_tier.value if hasattr(db_node.stake_tier, 'value') else str(db_node.stake_tier or "personal"),
        "quality_score": 0.9,
        "success_rate": 0.95,
    }
    
    # 更新到 NodeStatusStore，NodeStatusStore 会生成 cluster_id
    new_cluster_id = update_node_status(node_id, merged_status, capacity_info)
    
    # 如果生成了新的 cluster_id，更新 DB
    if new_cluster_id and db_node.cluster_id != new_cluster_id:
        node_repo.update(node_id, cluster_id=new_cluster_id)
        logger.info(f"Node {node_id} cluster assigned: {new_cluster_id}")
    
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

