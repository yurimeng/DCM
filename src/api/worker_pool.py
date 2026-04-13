"""
F11: Worker Pool - API 端点

无状态 Worker 管理接口
高度依赖网络状态，与 Scaler 协同工作
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from ..core.cluster import worker_pool_service, WorkerPoolService
from ..core.p2p import p2p_service
from ..core.relay import relay_service

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


# ==================== 请求/响应模型 ====================

class RegisterWorkerRequest(BaseModel):
    worker_id: str
    address: str
    port: int = 8000
    capabilities: List[str] = []


class HeartbeatRequest(BaseModel):
    status: str = "ready"
    current_requests: int = 0
    cpu_usage: float = 0
    memory_usage: float = 0


class WorkerResponse(BaseModel):
    worker_id: str
    address: str
    port: int
    status: str
    created_at: str
    idle_time_sec: int
    current_requests: int
    completed_requests: int


class WorkerListResponse(BaseModel):
    workers: List[WorkerResponse]
    total: int


class RegisterResponse(BaseModel):
    registered: bool
    worker_id: str
    sync_state: dict


class DrainResponse(BaseModel):
    draining: bool
    pending_requests: int


class DispatchRequestResponse(BaseModel):
    dispatched: bool
    worker_id: str
    endpoint: str


class PoolStatusResponse(BaseModel):
    total_workers: int
    by_status: dict
    total_requests: int
    total_completed: int
    network_status: dict
    relay_status: dict


# ==================== Worker 管理端点 ====================

@router.post("/register", response_model=RegisterResponse)
async def register_worker(request: RegisterWorkerRequest):
    """
    Worker 注册
    
    POST /api/v1/workers/register
    
    将 Worker 注册到 Worker Pool，并同步网络状态
    """
    # 注册 Worker
    worker = await worker_pool_service.register_worker(
        worker_id=request.worker_id,
        address=request.address,
        port=request.port
    )
    
    # 更新网络状态 - Worker 作为 P2P 对等节点
    await p2p_service.add_peer(
        peer_id=request.worker_id,
        addresses=[f"/ip4/{request.address}/tcp/{request.port}"],
        is_relay=False
    )
    
    # 获取当前状态同步
    sync_state = {
        "cluster_nodes": len(await p2p_service.get_all_peers()),
        "relay_available": relay_service.config.relay_enabled,
        "p2p_status": p2p_service.get_status()
    }
    
    return RegisterResponse(
        registered=True,
        worker_id=worker.worker_id,
        sync_state=sync_state
    )


@router.post("/{worker_id}/heartbeat")
async def worker_heartbeat(worker_id: str, request: HeartbeatRequest):
    """
    Worker 心跳
    
    POST /api/v1/workers/{worker_id}/heartbeat
    """
    success = await worker_pool_service.heartbeat(
        worker_id=worker_id,
        status=request.status,
        current_requests=request.current_requests
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker not found: {worker_id}"
        )
    
    return {"acknowledged": True}


@router.post("/{worker_id}/drain", response_model=DrainResponse)
async def drain_worker(worker_id: str):
    """
    Worker 下线 (平滑下线)
    
    POST /api/v1/workers/{worker_id}/drain
    
    停止接受新请求，等待现有请求完成后销毁
    """
    # 获取 Worker 状态
    worker = await worker_pool_service.get_worker(worker_id)
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker not found: {worker_id}"
        )
    
    if worker.status == "draining":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Worker already draining: {worker_id}"
        )
    
    # 启动 draining (异步)
    asyncio.create_task(_async_drain_worker(worker_id))
    
    return DrainResponse(
        draining=True,
        pending_requests=worker.current_requests
    )


async def _async_drain_worker(worker_id: str):
    """异步执行 Worker 下线"""
    try:
        await worker_pool_service.drain_worker(worker_id)
        
        # 从 P2P 网络移除
        await p2p_service.disconnect_peer(worker_id)
        
        logger.info(f"Worker drained and removed: {worker_id}")
    except Exception as e:
        logger.error(f"Worker drain failed: {e}")


@router.delete("/{worker_id}")
async def remove_worker(worker_id: str):
    """
    强制移除 Worker
    
    DELETE /api/v1/workers/{worker_id}
    """
    success = await worker_pool_service.remove_worker(worker_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker not found: {worker_id}"
        )
    
    # 从 P2P 网络移除
    await p2p_service.disconnect_peer(worker_id)
    
    return {"success": True, "worker_id": worker_id}


# ==================== Worker 查询端点 ====================

@router.get("/", response_model=WorkerListResponse)
async def list_workers(status_filter: Optional[str] = None):
    """
    列出所有 Worker
    
    GET /api/v1/workers/
    """
    workers = worker_pool_service.get_workers()
    
    if status_filter:
        workers = [w for w in workers if w["status"] == status_filter]
    
    return WorkerListResponse(
        workers=[WorkerResponse(**w) for w in workers],
        total=len(workers)
    )


@router.get("/{worker_id}")
async def get_worker(worker_id: str):
    """
    获取 Worker 详情
    
    GET /api/v1/workers/{worker_id}
    """
    worker = await worker_pool_service.get_worker(worker_id)
    
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker not found: {worker_id}"
        )
    
    # 获取网络诊断
    diagnostics = await relay_service.diagnose_connection(worker_id)
    
    return {
        "worker_id": worker.worker_id,
        "address": worker.address,
        "port": worker.port,
        "status": worker.status,
        "endpoint": worker.endpoint,
        "created_at": worker.created_at.isoformat(),
        "idle_time_sec": worker.idle_time_sec,
        "current_requests": worker.current_requests,
        "completed_requests": worker.completed_requests,
        "network_diagnostics": diagnostics
    }


# ==================== 请求分发端点 ====================

@router.post("/dispatch/{worker_id}", response_model=DispatchRequestResponse)
async def dispatch_request(worker_id: str):
    """
    分发请求到 Worker
    
    POST /api/v1/workers/dispatch/{worker_id}
    """
    success = await worker_pool_service.dispatch_request(worker_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker not found or not ready: {worker_id}"
        )
    
    worker = await worker_pool_service.get_worker(worker_id)
    
    return DispatchRequestResponse(
        dispatched=True,
        worker_id=worker_id,
        endpoint=worker.endpoint
    )


@router.post("/complete/{worker_id}")
async def complete_request(worker_id: str):
    """
    请求完成
    
    POST /api/v1/workers/complete/{worker_id}
    """
    success = await worker_pool_service.complete_request(worker_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker not found: {worker_id}"
        )
    
    return {"success": True}


@router.get("/select")
async def select_worker():
    """
    选择 Worker (最少连接优先)
    
    GET /api/v1/workers/select
    """
    worker = await worker_pool_service.select_worker()
    
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No ready workers available"
        )
    
    return {
        "worker_id": worker.worker_id,
        "endpoint": worker.endpoint,
        "current_requests": worker.current_requests
    }


# ==================== 状态端点 ====================

@router.get("/status/pool", response_model=PoolStatusResponse)
async def get_pool_status():
    """
    获取 Worker Pool 状态
    
    GET /api/v1/workers/status/pool
    
    包含网络状态和 Relay 状态
    """
    pool_status = worker_pool_service.get_status()
    
    # 获取网络状态
    p2p_status = p2p_service.get_status()
    relay_status = relay_service.get_status()
    
    return PoolStatusResponse(
        total_workers=pool_status["total_workers"],
        by_status=pool_status["by_status"],
        total_requests=pool_status["total_requests"],
        total_completed=pool_status["total_completed"],
        network_status={
            "peer_id": p2p_status.get("peer_id"),
            "connected_peers": p2p_status.get("connected_peers", 0)
        },
        relay_status={
            "relay_enabled": relay_status["relay_enabled"],
            "active_connections": relay_status["active_connections"]
        }
    )


# ==================== 健康检查端点 ====================

@router.get("/health")
async def health_check():
    """
    健康检查
    
    GET /api/v1/workers/health
    """
    pool_status = worker_pool_service.get_status()
    p2p_status = p2p_service.get_status()
    
    ready_workers = pool_status["by_status"].get("ready", 0) + \
                    pool_status["by_status"].get("busy", 0)
    
    return {
        "status": "healthy" if ready_workers > 0 else "degraded",
        "total_workers": pool_status["total_workers"],
        "ready_workers": ready_workers,
        "p2p_connected": p2p_status.get("connected_peers", 0) > 0
    }


# ==================== 日志导入 ====================

import logging
logger = logging.getLogger(__name__)
import asyncio
