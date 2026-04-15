"""
F11: Worker Pool - API 端点

无状态 Worker 管理接口
高度依赖网络状态，与 Scaler 协同工作

网络冗余机制:
- 心跳超时检测
- 自动重连
- 直连/Relay 切换
- 离线降级
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from ..core.cluster import worker_pool_service, WorkerPoolService
from ..core.p2p import p2p_service
from ..core.relay import relay_service
from src.exceptions import (
    ErrorCode,
    HTTPException,
    raise_not_found,
    raise_invalid_status,
    raise_validation_error,
    raise_bad_request,
    raise_internal_error,
)


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
    p2p_connected: bool
    connection_type: str
    relay_node: Optional[str]
    is_available: bool


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


class NetworkRedundancyStatus(BaseModel):
    total_workers: int
    available_workers: int
    unavailable_workers: int
    via_direct: int
    via_relay: int
    retrying: int
    relay_capacity: dict


class ReconnectResponse(BaseModel):
    worker_id: str
    reconnecting: bool
    attempt: int
    max_attempts: int


# ==================== Worker 管理端点 ====================

@router.post("/register", response_model=RegisterResponse)
async def register_worker(request: RegisterWorkerRequest):
    """
    Worker 注册
    
    POST /api/v1/workers/register
    
    将 Worker 注册到 Worker Pool，并同步网络状态
    尝试直连，失败后自动切换到 Relay
    """
    # 注册 Worker
    worker = await worker_pool_service.register_worker(
        worker_id=request.worker_id,
        address=request.address,
        port=request.port
    )
    
    # 获取当前状态同步
    sync_state = {
        "cluster_nodes": len(await p2p_service.get_all_peers()),
        "relay_available": relay_service.config.relay_enabled,
        "p2p_status": p2p_service.get_status(),
        "connection_type": worker.connection_type,
        "relay_node": worker.relay_node,
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
    
    心跳恢复网络连接状态
    """
    success = await worker_pool_service.heartbeat(
        worker_id=worker_id,
        status=request.status,
        current_requests=request.current_requests
    )
    
    if not success:
        raise_not_found("Worker not found", worker_id)
    
    return {"acknowledged": True}


@router.post("/{worker_id}/drain", response_model=DrainResponse)
async def drain_worker(worker_id: str):
    """
    Worker 下线 (平滑下线)
    
    POST /api/v1/workers/{worker_id}/drain
    
    停止接受新请求，等待现有请求完成后销毁
    """
    worker = await worker_pool_service.get_worker(worker_id)
    if not worker:
        raise_not_found("Worker not found", worker_id)
    
    if worker.status == "draining":
        raise_bad_request("Worker already draining: {worker_id}")
    
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
        await p2p_service.disconnect_peer(worker_id)
        logger.info(f"Worker drained and removed: {worker_id}")
    except Exception as e:
        logger.error(f"Worker drain failed: {e}")


@router.delete("/{worker_id}")
async def remove_worker(worker_id: str):
    """强制移除 Worker"""
    success = await worker_pool_service.remove_worker(worker_id)
    
    if not success:
        raise_not_found("Worker not found", worker_id)
    
    await p2p_service.disconnect_peer(worker_id)
    
    return {"success": True, "worker_id": worker_id}


# ==================== Worker 查询端点 ====================

@router.get("/", response_model=WorkerListResponse)
async def list_workers(status_filter: Optional[str] = None,
                       network_filter: Optional[str] = None):
    """
    列出所有 Worker
    
    GET /api/v1/workers/
    
    Query params:
    - status_filter: 状态过滤 (creating, ready, busy, draining)
    - network_filter: 网络状态过滤 (available, unavailable, direct, relay)
    """
    workers = worker_pool_service.get_workers()
    
    # 状态过滤
    if status_filter:
        workers = [w for w in workers if w["status"] == status_filter]
    
    # 网络状态过滤
    if network_filter:
        if network_filter == "available":
            workers = [w for w in workers if w["is_available"]]
        elif network_filter == "unavailable":
            workers = [w for w in workers if not w["p2p_connected"]]
        elif network_filter == "direct":
            workers = [w for w in workers if w["connection_type"] == "direct"]
        elif network_filter == "relay":
            workers = [w for w in workers if w["connection_type"] == "relayed"]
    
    return WorkerListResponse(
        workers=[WorkerResponse(**w) for w in workers],
        total=len(workers)
    )


@router.get("/{worker_id}")
async def get_worker(worker_id: str):
    """获取 Worker 详情"""
    worker = await worker_pool_service.get_worker(worker_id)
    
    if not worker:
        raise_not_found("Worker not found", worker_id)
    
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
        # 网络状态
        "p2p_connected": worker.p2p_connected,
        "connection_type": worker.connection_type,
        "relay_node": worker.relay_node,
        "is_available": worker.is_available,
        # 冗余机制
        "retry_count": worker.retry_count,
        "max_retry_count": worker.max_retry_count,
        "network_failures": worker.network_failures,
        "heartbeat_timeout": worker.heartbeat_timeout,
        "network_diagnostics": diagnostics
    }


# ==================== 请求分发端点 ====================

@router.post("/dispatch/{worker_id}")
async def dispatch_request(worker_id: str):
    """分发请求到 Worker"""
    success = await worker_pool_service.dispatch_request(worker_id)
    
    if not success:
        raise_not_found("Worker not found or not available", worker_id)
    
    worker = await worker_pool_service.get_worker(worker_id)
    
    return {
        "dispatched": True,
        "worker_id": worker_id,
        "endpoint": worker.endpoint,
        "connection_type": worker.connection_type
    }


@router.post("/complete/{worker_id}")
async def complete_request(worker_id: str):
    """请求完成"""
    success = await worker_pool_service.complete_request(worker_id)
    
    if not success:
        raise_not_found("Worker not found", worker_id)
    
    return {"success": True}


@router.get("/select")
async def select_worker():
    """
    选择 Worker (最少连接优先)
    
    GET /api/v1/workers/select
    
    只选择网络可达的 Worker
    """
    worker = await worker_pool_service.select_worker()
    
    if not worker:
        raise_bad_request("No available workers"
        )
    
    return {
        "worker_id": worker.worker_id,
        "endpoint": worker.endpoint,
        "current_requests": worker.current_requests,
        "connection_type": worker.connection_type,
        "relay_node": worker.relay_node
    }


# ==================== 网络冗余端点 ====================

@router.get("/network/redundancy", response_model=NetworkRedundancyStatus)
async def get_network_redundancy_status():
    """
    获取网络冗余状态
    
    GET /api/v1/workers/network/redundancy
    
    显示所有 Worker 的网络连接状态和 Relay 容量
    """
    pool_status = worker_pool_service.get_status()
    network_stats = pool_status["network_stats"]
    
    # 获取 Relay 容量
    relay_nodes = await relay_service.get_all_relay_nodes()
    relay_capacities = []
    
    for node in relay_nodes:
        capacity = await relay_service.get_relay_node_capacity(node.peer_id)
        relay_capacities.append({
            "peer_id": node.peer_id,
            "status": node.status.value,
            "active_connections": node.active_connections,
            **capacity
        })
    
    # 统计可用 Worker
    workers = worker_pool_service.get_workers()
    available = sum(1 for w in workers if w["is_available"])
    unavailable = sum(1 for w in workers if not w["p2p_connected"])
    
    return NetworkRedundancyStatus(
        total_workers=pool_status["total_workers"],
        available_workers=available,
        unavailable_workers=unavailable,
        via_direct=network_stats["via_direct"],
        via_relay=network_stats["via_relay"],
        retrying=network_stats["retrying"],
        relay_capacity={
            "total_nodes": len(relay_nodes),
            "nodes": relay_capacities
        }
    )


@router.post("/{worker_id}/reconnect")
async def reconnect_worker(worker_id: str):
    """
    手动重连 Worker
    
    POST /api/v1/workers/{worker_id}/reconnect
    
    强制尝试重连不可用的 Worker
    """
    worker = await worker_pool_service.get_worker(worker_id)
    
    if not worker:
        raise_not_found("Worker not found", worker_id)
    
    if worker.p2p_connected:
        return {
            "worker_id": worker_id,
            "reconnecting": False,
            "message": "Worker already connected"
        }
    
    if not worker.can_retry:
        raise_bad_request("Worker max retry count exceeded: {worker.max_retry_count}")
    
    # 触发重连
    worker.last_reconnect_attempt = None  # 允许立即重连
    await worker_pool_service._try_reconnect_workers()
    
    # 重新获取状态
    worker = await worker_pool_service.get_worker(worker_id)
    
    return ReconnectResponse(
        worker_id=worker_id,
        reconnecting=True,
        attempt=worker.retry_count if worker else 0,
        max_attempts=worker.max_retry_count if worker else 5
    )


# ==================== 状态端点 ====================

@router.get("/status/pool")
async def get_pool_status():
    """
    获取 Worker Pool 状态
    
    GET /api/v1/workers/status/pool
    
    包含网络状态和 Relay 状态
    """
    pool_status = worker_pool_service.get_status()
    p2p_status = p2p_service.get_status()
    relay_status = relay_service.get_status()
    
    return {
        **pool_status,
        "network_status": {
            "peer_id": p2p_status.get("peer_id"),
            "connected_peers": p2p_status.get("connected_peers", 0)
        },
        "relay_status": {
            "relay_enabled": relay_status["relay_enabled"],
            "active_connections": relay_status["active_connections"],
            "relay_nodes": relay_status["relay_nodes_count"]
        }
    }


@router.get("/health")
async def health_check():
    """
    健康检查
    
    GET /api/v1/workers/health
    """
    pool_status = worker_pool_service.get_status()
    p2p_status = p2p_service.get_status()
    workers = worker_pool_service.get_workers()
    
    ready_workers = pool_status["by_status"].get("ready", 0) + \
                    pool_status["by_status"].get("busy", 0)
    
    # 检查网络冗余
    network_redundant = pool_status["network_stats"]["via_relay"] > 0 or \
                        pool_status["network_stats"]["via_direct"] > 0
    
    return {
        "status": "healthy" if ready_workers > 0 and network_redundant else "degraded",
        "total_workers": pool_status["total_workers"],
        "ready_workers": ready_workers,
        "p2p_connected": p2p_status.get("connected_peers", 0) > 0,
        "network_redundant": network_redundant,
        "via_direct": pool_status["network_stats"]["via_direct"],
        "via_relay": pool_status["network_stats"]["via_relay"],
        "unavailable": pool_status["network_stats"]["unavailable"]
    }


# ==================== 日志导入 ====================

import logging
logger = logging.getLogger(__name__)
import asyncio
