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

from ..database import get_db
from ..models import Node, NodeCreate, NodeResponse, NodeStatus, NodePollResponse, NodeResultSubmit
from ..models.db_models import NodeDB, NodeStatusDB, StakeRecordDB, MatchDB
from ..repositories import NodeRepository, MatchRepository, JobRepository, EscrowRepository
from ..services import matching_service, escrow_service, verification_service, stake_service
from config import settings

router = APIRouter(prefix="/nodes", tags=["nodes"])


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
    注册新节点
    
    返回所需的 Stake 门槛
    """
    # 1. 创建 Node Pydantic 模型
    node_data = node_create.model_dump()
    
    # 生成唯一的 node_id
    node_data['node_id'] = str(uuid.uuid4())
    
    # 预留扩展字段 (metadata) - 未来可用于用户绑定、钱包地址等
    node_data['metadata'] = {
        'user_id': None,           # 未来绑定用户
        'wallet_address': None,    # 未来绑定钱包
        'tags': [],                # 自定义标签
    }
    
    node = Node(**node_data)
    
    # 2. 保存到数据库
    node_repo = NodeRepository(db)
    db_node = node_repo.create(node)
    
    # 3. 注册到撮合引擎（内存）
    matching_service.register_node(node)
    
    # 4. 响应
    return NodeResponse(
        node_id=node.node_id,
        status=NodeStatus(_safe_status(db_node.status)),
        stake_required=db_node.stake_required,
        stake_amount=db_node.stake_amount,
        gpu_count=node.gpu_count,
        slot_count=len(node.slot_ids),
        worker_count=len(node.worker_ids),
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
    
    # 注册节点到撮合引擎（内存服务）
    from ..models import Node
    import json
    node_model = Node(
        node_id=node_id,
        gpu_type=db_node.gpu_type,
        vram_gb=db_node.vram_gb,
        model_support=json.loads(db_node.model_support) if isinstance(db_node.model_support, str) else (db_node.model_support or []),
        ask_price=float(db_node.ask_price),
        avg_latency=int(db_node.avg_latency),
        region=db_node.region,
    )
    node_model.status = NodeStatus.ONLINE
    matching_service.register_node(node_model)
    
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
    
    # 更新内存服务
    matching_service.update_node_status(node_id, NodeStatus.OFFLINE)
    matching_service.unregister_node(node_id)
    
    return {
        "node_id": node_id,
        "status": NodeStatus.OFFLINE.value,
        "message": "Node is now offline"
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
    
    # 检查节点是否在线
    if db_node.status != NodeStatusDB.ONLINE:
        return NodePollResponse(has_job=False)
    
    # 触发撮合（内存服务）
    match = matching_service.poll_node(node_id)
    
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
            model=model_info,
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
    
    job = Job(
        model=db_job.model,
        input_tokens=db_job.input_tokens,
        output_tokens_limit=db_job.output_tokens_limit,
        max_latency=db_job.max_latency,
        bid_price=float(db_job.bid_price),
    )
    job.job_id = db_job.job_id
    
    # Layer 1 验证
    layer1_passed, _ = verification_service.verify_layer1(
        match=match,
        job=job,
        result=result_submit.result,
        result_hash=result_submit.result_hash,
        actual_latency_ms=result_submit.actual_latency_ms,
        actual_output_tokens=result_submit.actual_output_tokens,
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
        actual_output_tokens=result_submit.actual_output_tokens,
        actual_latency_ms=result_submit.actual_latency_ms,
        completed_at=datetime.utcnow()
    )
    
    # 自动触发结算
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
            platform_fee = actual_cost * 0.05  # 5%
            node_earn = actual_cost * 0.95   # 95%
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
    """
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # 更新心跳时间
    node_repo.update_heartbeat(node_id)
    
    # 同步到 matching_service 内存状态
    if db_node.status == NodeStatusDB.ONLINE:
        from ..models import Node
        node = Node(
            node_id=db_node.node_id,
            gpu_type=db_node.gpu_type,
            vram_gb=db_node.vram_gb,
            model_support=json.loads(db_node.model_support) if isinstance(db_node.model_support, str) else (db_node.model_support or []),
            ask_price=float(db_node.ask_price),
            avg_latency=int(db_node.avg_latency),
            region=db_node.region,
        )
        matching_service.register_node(node)
        matching_service.update_node_status(node_id, NodeStatus.ONLINE)
    
    # 检查节点是否在 matching_service 中
    re_register = False
    if node_id not in matching_service._online_nodes:
        # 节点不在内存中，尝试重新注册
        if db_node.status == NodeStatusDB.ONLINE:
            from ..models import Node
            node = Node(
                node_id=db_node.node_id,
                gpu_type=db_node.gpu_type,
                vram_gb=db_node.vram_gb,
                model_support=json.loads(db_node.model_support) if isinstance(db_node.model_support, str) else (db_node.model_support or []),
                ask_price=float(db_node.ask_price),
                avg_latency=int(db_node.avg_latency),
                region=db_node.region,
            )
            try:
                matching_service.register_node(node)
                matching_service.update_node_status(node_id, NodeStatus.ONLINE)
            except:
                re_register = True
        else:
            re_register = True
    
    return {
        "node_id": node_id,
        "status": heartbeat_data.get("status", "idle"),
        "timestamp": int(datetime.utcnow().timestamp() * 1000),
        "matched": node_id in matching_service._online_nodes,
        "re_register": re_register,
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
