"""
F15: Relay Service - API 端点

Relay 状态与诊断接口
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from ..core.relay import relay_service, RelayConfig

router = APIRouter(prefix="/api/v1/relay", tags=["relay"])


# ==================== 请求/响应模型 ====================

class RelayNodeResponse(BaseModel):
    peer_id: str
    status: str
    active_connections: int
    bandwidth_usage_percent: float


class RelayStatusResponse(BaseModel):
    relay_enabled: bool
    active_connections: int
    max_connections: int
    relay_candidates: List[str]


class RelayConnectionResponse(BaseModel):
    connection_id: str
    source_peer_id: str
    target_peer_id: str
    relay_node: str
    connection_type: str
    bytes_sent: int
    bytes_received: int
    age_seconds: float


class RelayDiagnosticsResponse(BaseModel):
    peer_id: str
    connection_type: str
    relay_node: Optional[str]
    latency_ms: Optional[float]


class RelayCapacityResponse(BaseModel):
    available: bool
    reason: Optional[str] = None
    active_connections: Optional[int] = None
    max_connections: Optional[int] = None
    bandwidth_usage_percent: Optional[float] = None
    remaining_capacity: Optional[int] = None


class RelayMetricsResponse(BaseModel):
    total_relay_requests: int
    successful_relays: int
    failed_relays: int
    active_relay_connections: int
    total_bytes_relayed: int
    avg_relay_latency_ms: float


# ==================== Relay 状态端点 ====================

@router.get("/status", response_model=RelayStatusResponse)
async def get_relay_status():
    """
    获取 Relay 状态
    
    GET /api/v1/relay/status
    """
    status_info = relay_service.get_status()
    
    # 获取 Relay 节点列表
    relay_nodes = await relay_service.get_all_relay_nodes()
    relay_candidates = [
        f"{node.peer_id} (core)"
        for node in relay_nodes
        if node.status.value in ("enabled", "active")
    ]
    
    return RelayStatusResponse(
        relay_enabled=status_info["relay_enabled"],
        active_connections=status_info["active_connections"],
        max_connections=relay_service.config.max_connections_per_relay,
        relay_candidates=relay_candidates
    )


@router.get("/nodes")
async def list_relay_nodes():
    """
    列出所有 Relay 节点
    
    GET /api/v1/relay/nodes
    """
    nodes = await relay_service.get_all_relay_nodes()
    
    return {
        "nodes": [
            {
                "peer_id": node.peer_id,
                "status": node.status.value,
                "active_connections": node.active_connections,
                "bandwidth_usage_percent": round(node.bandwidth_usage_percent, 2),
                "last_seen": node.last_seen.isoformat()
            }
            for node in nodes
        ],
        "total": len(nodes)
    }


@router.get("/nodes/{peer_id}")
async def get_relay_node(peer_id: str):
    """
    获取 Relay 节点详情
    
    GET /api/v1/relay/nodes/{peer_id}
    """
    node = await relay_service.get_relay_node(peer_id)
    
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Relay node not found: {peer_id}"
        )
    
    return {
        "peer_id": node.peer_id,
        "addresses": node.addresses,
        "status": node.status.value,
        "active_connections": node.active_connections,
        "total_connections": node.total_connections,
        "bandwidth_usage_percent": round(node.bandwidth_usage_percent, 2),
        "is_available": node.is_available
    }


@router.post("/nodes/register")
async def register_relay_node(peer_id: str, addresses: List[str]):
    """
    注册 Relay 节点
    
    POST /api/v1/relay/nodes/register
    """
    node = await relay_service.register_relay_node(peer_id, addresses)
    
    return {
        "success": True,
        "peer_id": node.peer_id,
        "status": node.status.value
    }


@router.delete("/nodes/{peer_id}")
async def unregister_relay_node(peer_id: str):
    """
    取消注册 Relay 节点
    
    DELETE /api/v1/relay/nodes/{peer_id}
    """
    await relay_service.unregister_relay_node(peer_id)
    
    return {
        "success": True,
        "peer_id": peer_id
    }


# ==================== 连接诊断端点 ====================

@router.get("/diagnostics", response_model=RelayDiagnosticsResponse)
async def diagnose_connection(peer_id: str):
    """
    诊断连接类型
    
    GET /api/v1/relay/diagnostics?peer_id=QmXYZ...
    """
    diagnostics = await relay_service.diagnose_connection(peer_id)
    
    if not diagnostics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No connection info for peer: {peer_id}"
        )
    
    return RelayDiagnosticsResponse(
        peer_id=diagnostics["peer_id"],
        connection_type=diagnostics["connection_type"],
        relay_node=diagnostics["relay_node"],
        latency_ms=diagnostics.get("age_seconds", 0) * 1000 if diagnostics.get("age_seconds") else None
    )


@router.get("/connections")
async def list_relay_connections():
    """
    列出所有 Relay 连接
    
    GET /api/v1/relay/connections
    """
    status_info = relay_service.get_status()
    
    return {
        "active_connections": status_info["active_connections"],
        "max_connections": relay_service.config.max_connections_per_relay
    }


@router.get("/capacity/{relay_node}", response_model=RelayCapacityResponse)
async def get_relay_capacity(relay_node: str):
    """
    获取 Relay 节点容量
    
    GET /api/v1/relay/capacity/{relay_node}
    """
    capacity = await relay_service.get_relay_node_capacity(relay_node)
    return RelayCapacityResponse(**capacity)


# ==================== 指标端点 ====================

@router.get("/metrics", response_model=RelayMetricsResponse)
async def get_relay_metrics():
    """
    获取 Relay 指标
    
    GET /api/v1/relay/metrics
    """
    metrics = relay_service.get_metrics()
    return RelayMetricsResponse(**metrics)


@router.get("/health")
async def health_check():
    """
    健康检查
    
    GET /api/v1/relay/health
    """
    status_info = relay_service.get_status()
    
    return {
        "status": "healthy" if status_info["relay_enabled"] else "disabled",
        "relay_enabled": status_info["relay_enabled"],
        "relay_nodes": status_info["relay_nodes_count"],
        "active_connections": status_info["active_connections"]
    }


# ==================== 配置端点 ====================

@router.get("/config")
async def get_relay_config():
    """
    获取 Relay 配置
    
    GET /api/v1/relay/config
    """
    return {
        "relay_enabled": relay_service.config.relay_enabled,
        "max_connections_per_relay": relay_service.config.max_connections_per_relay,
        "per_connection_limit_bps": relay_service.config.per_connection_limit_bps,
        "per_worker_limit_bps": relay_service.config.per_worker_limit_bps,
        "per_relay_total_limit_bps": relay_service.config.per_relay_total_limit_bps,
        "prefer_direct": relay_service.config.prefer_direct,
        "auto_reconnect": relay_service.config.auto_reconnect
    }
