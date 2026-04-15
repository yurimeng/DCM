"""
F9: Core Cluster - API 端点

集群管理接口
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from ..core.cluster import cluster_service, CoreClusterService, ClusterConfig
from ..core.p2p import p2p_service
from src.exceptions import (
    ErrorCode,
    HTTPException,
    raise_not_found,
    raise_invalid_status,
    raise_validation_error,
    raise_bad_request,
    raise_internal_error,
)


router = APIRouter(prefix="/api/v1/core", tags=["core"])


# ==================== 请求/响应模型 ====================

class RegisterNodeRequest(BaseModel):
    address: str
    port: int = 8000
    weight: int = 1


class HeartbeatRequest(BaseModel):
    cpu_usage: float = 0
    memory_usage: float = 0
    active_connections: int = 0


class NodeResponse(BaseModel):
    node_id: str
    address: str
    port: int
    weight: int
    status: str
    healthy: bool
    cpu_usage: float
    memory_usage: float
    active_connections: int
    last_heartbeat: str


class NodeListResponse(BaseModel):
    nodes: List[NodeResponse]
    total: int


class HealthResponse(BaseModel):
    status: str
    nodes: dict
    quorum: int
    available: int


class SyncRequest(BaseModel):
    type: str  # job_update, node_state, etc
    data: dict
    timestamp: Optional[float] = None


class SyncResponse(BaseModel):
    synced: bool
    peers: int


class MetricsResponse(BaseModel):
    total_nodes: int
    healthy_nodes: int
    online_nodes: int
    total_requests: int
    avg_latency_ms: float


# ==================== 节点管理端点 ====================

@router.get("/nodes", response_model=NodeListResponse)
async def list_nodes():
    """
    获取 Core 节点列表
    
    GET /api/v1/core/nodes
    """
    nodes = await cluster_service.get_all_nodes()
    
    return NodeListResponse(
        nodes=[
            NodeResponse(
                node_id=node.node_id,
                address=node.address,
                port=node.port,
                weight=node.weight,
                status=node.status.value,
                healthy=node.healthy,
                cpu_usage=node.cpu_usage,
                memory_usage=node.memory_usage,
                active_connections=node.active_connections,
                last_heartbeat=node.last_heartbeat.isoformat()
            )
            for node in nodes
        ],
        total=len(nodes)
    )


@router.post("/nodes/register")
async def register_node(request: RegisterNodeRequest):
    """
    注册 Core 节点
    
    POST /api/v1/core/nodes/register
    """
    node = await cluster_service.register_node(
        address=request.address,
        port=request.port,
        weight=request.weight
    )
    
    # 注册到 P2P 网络
    await p2p_service.add_peer(
        peer_id=node.node_id,
        addresses=[f"/ip4/{node.address}/tcp/{node.port}"],
        is_relay=True  # Core 节点兼任 Relay
    )
    
    return {
        "success": True,
        "node_id": node.node_id,
        "address": f"{node.address}:{node.port}"
    }


@router.post("/nodes/{node_id}/heartbeat")
async def node_heartbeat(node_id: str, request: HeartbeatRequest):
    """
    节点心跳
    
    POST /api/v1/core/nodes/{node_id}/heartbeat
    """
    success = await cluster_service.heartbeat(
        node_id=node_id,
        cpu_usage=request.cpu_usage,
        memory_usage=request.memory_usage,
        active_connections=request.active_connections
    )
    
    if not success:
        raise_not_found("resource", "Node not found: {node_id}")
    
    return {"success": True, "node_id": node_id}


@router.delete("/nodes/{node_id}")
async def remove_node(node_id: str):
    """
    移除节点
    
    DELETE /api/v1/core/nodes/{node_id}
    """
    success = await cluster_service.remove_node(node_id)
    
    if not success:
        raise_not_found("resource", "Node not found: {node_id}")
    
    # 从 P2P 网络断开
    await p2p_service.disconnect_peer(node_id)
    
    return {"success": True, "node_id": node_id}


# ==================== 健康检测端点 ====================

@router.get("/health", response_model=HealthResponse)
async def get_health():
    """
    获取集群健康状态
    
    GET /api/v1/core/health
    """
    # 检查所有节点健康状态
    await cluster_service.check_all_nodes_health()
    
    nodes = await cluster_service.get_all_nodes()
    healthy_nodes = await cluster_service.get_healthy_nodes()
    
    node_status = {
        node.node_id: {
            "status": node.status.value,
            "latency_ms": node.latency_ms,
            "healthy": node.healthy
        }
        for node in nodes
    }
    
    quorum = cluster_service.config.quorum
    available = len(healthy_nodes)
    
    return HealthResponse(
        status="healthy" if available >= quorum else "degraded",
        nodes=node_status,
        quorum=quorum,
        available=available
    )


# ==================== P2P 同步端点 ====================

@router.post("/sync", response_model=SyncResponse)
async def sync_data(request: SyncRequest):
    """
    P2P 同步数据
    
    POST /api/v1/core/sync
    
    将数据同步到其他 Core 节点
    """
    # 通过 P2P 网络广播
    if request.type == "job_update":
        from ..core.p2p import JobUpdate
        update = JobUpdate(
            sender_id=cluster_service._node_id or "self",
            data=request.data
        )
        await p2p_service.broadcast_job_update(update)
    
    elif request.type == "node_state":
        from ..core.p2p import NodeState
        state = NodeState(
            sender_id=cluster_service._node_id or "self",
            data=request.data
        )
        await p2p_service.broadcast_node_state(state)
    
    # 获取已连接的对等节点数量
    connected_peers = await p2p_service.get_connected_peers()
    
    return SyncResponse(
        synced=True,
        peers=len(connected_peers)
    )


# ==================== 路由端点 ====================

@router.get("/select")
async def select_node():
    """
    选择节点（路由）
    
    GET /api/v1/core/select
    
    基于路由策略选择一个健康节点
    """
    node = await cluster_service.select_node()
    
    if not node:
        raise_internal_error("No healthy nodes available")
    
    return {
        "node_id": node.node_id,
        "address": node.address,
        "port": node.port,
        "weight": node.weight
    }


# ==================== 指标端点 ====================

@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取集群指标
    
    GET /api/v1/core/metrics
    """
    metrics = cluster_service.get_metrics()
    return MetricsResponse(**metrics)


@router.get("/quorum")
async def check_quorum():
    """
    检查是否满足多数节点要求
    
    GET /api/v1/core/quorum
    """
    is_met = await cluster_service.is_quorum_met()
    healthy_count = len(await cluster_service.get_healthy_nodes())
    required = cluster_service.config.quorum
    
    return {
        "quorum_met": is_met,
        "healthy_nodes": healthy_count,
        "required": required
    }


@router.get("/config")
async def get_config():
    """
    获取集群配置
    
    GET /api/v1/core/config
    """
    return {
        "routing_strategy": cluster_service.config.routing_strategy.value,
        "quorum": cluster_service.config.quorum,
        "heartbeat_timeout_sec": cluster_service.config.heartbeat_timeout_sec,
        "max_consecutive_failures": cluster_service.config.max_consecutive_failures
    }


@router.get("/health_check")
async def health_check():
    """
    健康检查
    
    GET /api/v1/core/health_check
    """
    return {
        "status": "healthy",
        "service": "CoreClusterService",
        "nodes_count": len(await cluster_service.get_all_nodes())
    }
