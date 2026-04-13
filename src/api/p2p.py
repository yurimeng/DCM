"""
F13: Core P2P Network - API 端点

P2P 网络管理接口
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional

from ..core.p2p import p2p_service, P2PConfig, PeerInfo

router = APIRouter(prefix="/api/v1/p2p", tags=["p2p"])


# ==================== 请求/响应模型 ====================

class AddPeerRequest(BaseModel):
    peer_id: str
    addresses: List[str]
    is_relay: bool = False


class ConnectPeerRequest(BaseModel):
    peer_id: str
    relay_node: Optional[str] = None


class BroadcastJobUpdateRequest(BaseModel):
    job_id: str
    status: str
    match_id: str = ""


class BroadcastNodeStateRequest(BaseModel):
    node_id: str
    state: dict


class P2PInfoResponse(BaseModel):
    peer_id: str
    addresses: List[str]
    connected_peers: int
    relay_enabled: bool


class PeerResponse(BaseModel):
    peer_id: str
    address: str
    status: str
    is_relay: bool
    relay_node: Optional[str] = None
    latency_ms: float
    last_seen: str


class P2PConnectionsResponse(BaseModel):
    peers: List[PeerResponse]
    relays_in_use: int


class P2PStatusResponse(BaseModel):
    running: bool
    peer_id: str
    total_peers: int
    connected_peers: int
    relay_enabled: bool
    metrics: dict


class BroadcastResponse(BaseModel):
    success: bool
    recipients: int
    topic: str


# ==================== P2P 信息端点 ====================

@router.get("/info", response_model=P2PInfoResponse)
async def get_p2p_info():
    """获取本地 P2P 节点信息"""
    info = p2p_service.get_info()
    return P2PInfoResponse(**info)


@router.get("/connections", response_model=P2PConnectionsResponse)
async def get_p2p_connections():
    """获取 P2P 连接状态"""
    connections = p2p_service.get_connections()
    return connections


@router.get("/status", response_model=P2PStatusResponse)
async def get_p2p_status():
    """获取 P2P 服务状态"""
    status = p2p_service.get_status()
    return status


@router.get("/peers", response_model=List[PeerResponse])
async def list_peers():
    """列出所有 P2P 节点"""
    peers = await p2p_service.get_all_peers()
    return [
        PeerResponse(
            peer_id=p.peer_id,
            address=p.addresses[0] if p.addresses else "",
            status=p.status.value,
            is_relay=p.is_relay,
            relay_node=p.relay_node,
            latency_ms=p.latency_ms,
            last_seen=p.last_seen.isoformat()
        )
        for p in peers
    ]


# ==================== P2P 管理端点 ====================

@router.post("/peers/add")
async def add_peer(request: AddPeerRequest):
    """添加 P2P 节点"""
    peer = await p2p_service.add_peer(
        peer_id=request.peer_id,
        addresses=request.addresses,
        is_relay=request.is_relay
    )
    return {"success": True, "peer_id": peer.peer_id}


@router.post("/peers/connect")
async def connect_peer(request: ConnectPeerRequest):
    """连接 P2P 节点"""
    success = await p2p_service.connect_peer(
        peer_id=request.peer_id,
        relay_node=request.relay_node
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to connect to peer: {request.peer_id}"
        )
    
    return {"success": True, "peer_id": request.peer_id}


@router.post("/peers/disconnect")
async def disconnect_peer(peer_id: str):
    """断开 P2P 节点"""
    await p2p_service.disconnect_peer(peer_id)
    return {"success": True, "peer_id": peer_id}


# ==================== Pub/Sub 广播端点 ====================

@router.post("/broadcast/job_update", response_model=BroadcastResponse)
async def broadcast_job_update(request: BroadcastJobUpdateRequest):
    """广播 Job 更新 (gossipsub job_update)"""
    recipients = await p2p_service.broadcast_job_update(
        job_id=request.job_id,
        status=request.status,
        match_id=request.match_id
    )
    
    return BroadcastResponse(
        success=True,
        recipients=recipients,
        topic="job_update"
    )


@router.post("/broadcast/node_state", response_model=BroadcastResponse)
async def broadcast_node_state(request: BroadcastNodeStateRequest):
    """广播节点状态 (gossipsub node_state)"""
    recipients = await p2p_service.broadcast_node_state(
        node_id=request.node_id,
        state=request.state
    )
    
    return BroadcastResponse(
        success=True,
        recipients=recipients,
        topic="node_state"
    )


# ==================== 配置端点 ====================

@router.get("/config")
async def get_config():
    """获取 P2P 配置"""
    return {
        "listen_addresses": p2p_service.config.listen_addresses,
        "bootstrap_nodes": p2p_service.config.bootstrap_nodes,
        "heartbeat_interval_sec": p2p_service.config.heartbeat_interval_sec,
        "node_timeout_sec": p2p_service.config.node_timeout_sec,
        "max_retry_count": p2p_service.config.max_retry_count,
        "relay_enabled": p2p_service.config.relay_enabled,
        "topics": p2p_service.config.topics
    }


@router.post("/config/update")
async def update_config(heartbeat_interval_sec: int = None,
                       node_timeout_sec: int = None,
                       relay_enabled: bool = None):
    """更新 P2P 配置"""
    if heartbeat_interval_sec is not None:
        p2p_service.config.heartbeat_interval_sec = heartbeat_interval_sec
    
    if node_timeout_sec is not None:
        p2p_service.config.node_timeout_sec = node_timeout_sec
    
    if relay_enabled is not None:
        p2p_service.config.relay_enabled = relay_enabled
    
    return {"success": True}
