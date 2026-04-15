"""
F13: Core P2P Network - API 端点

P2P 连接管理接口
集成 F15 Relay Service
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from ..core.p2p import p2p_service, P2PConfig
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
    node_id: str
    match_id: Optional[str] = None
    result_hash: Optional[str] = None


class BroadcastNodeStateRequest(BaseModel):
    node_id: str
    status: str
    gpu_available: bool
    gpu_type: Optional[str] = None
    vram_gb: Optional[float] = None
    current_jobs: int = 0


class P2PInfoResponse(BaseModel):
    peer_id: Optional[str]
    listen_addresses: List[str]
    connected_peers: int
    relay_enabled: bool


class P2PStatusResponse(BaseModel):
    running: bool
    peer_id: Optional[str]
    total_peers: int
    connected_peers: int
    relay_enabled: bool
    metrics: dict


# ==================== 节点信息端点 ====================

@router.get("/info", response_model=P2PInfoResponse)
async def get_p2p_info():
    """
    获取本地 P2P 节点信息
    
    GET /api/v1/p2p/info
    """
    info = p2p_service.get_info()
    return P2PInfoResponse(**info)


@router.get("/connections")
async def get_connections():
    """
    获取连接状态
    
    GET /api/v1/p2p/connections
    """
    return p2p_service.get_connections()


@router.get("/status", response_model=P2PStatusResponse)
async def get_p2p_status():
    """
    获取 P2P 服务状态
    
    GET /api/v1/p2p/status
    """
    return p2p_service.get_status()


# ==================== 节点管理端点 ====================

@router.get("/peers")
async def list_peers():
    """
    列出所有 P2P 节点
    
    GET /api/v1/p2p/peers
    """
    peers = await p2p_service.get_all_peers()
    return {
        "peers": [
            {
                "peer_id": p.peer_id,
                "addresses": p.addresses,
                "status": p.status.value,
                "is_relay": p.is_relay,
                "relay_node": p.relay_node,
                "latency_ms": p.latency_ms,
                "last_seen": p.last_seen.isoformat()
            }
            for p in peers
        ],
        "total": len(peers)
    }


@router.post("/peers/add")
async def add_peer(request: AddPeerRequest):
    """
    添加 P2P 节点
    
    POST /api/v1/p2p/peers/add
    """
    peer = await p2p_service.add_peer(
        peer_id=request.peer_id,
        addresses=request.addresses,
        is_relay=request.is_relay
    )
    
    # 如果是 relay 节点，注册到 RelayService
    if request.is_relay:
        await relay_service.register_relay_node(request.peer_id, request.addresses)
    
    return {
        "success": True,
        "peer_id": peer.peer_id,
        "status": peer.status.value
    }


@router.post("/peers/connect")
async def connect_peer(request: ConnectPeerRequest):
    """
    连接 P2P 节点 (直连优先 + Relay 兜底)
    
    POST /api/v1/p2p/peers/connect
    """
    connected = await p2p_service.connect_peer(
        peer_id=request.peer_id,
        relay_node=request.relay_node
    )
    
    if connected:
        return {
            "success": True,
            "peer_id": request.peer_id,
            "connection_type": "relay" if await p2p_service.get_peer(request.peer_id) and 
                                (await p2p_service.get_peer(request.peer_id)).relay_node else "direct"
        }
    else:
        raise_internal_error("Failed to connect to peer: {request.peer_id}")


@router.post("/peers/disconnect")
async def disconnect_peer(peer_id: str):
    """
    断开 P2P 节点
    
    POST /api/v1/p2p/peers/disconnect
    """
    await p2p_service.disconnect_peer(peer_id)
    
    return {
        "success": True,
        "peer_id": peer_id
    }


# ==================== 广播端点 ====================

@router.post("/broadcast/job_update")
async def broadcast_job_update(request: BroadcastJobUpdateRequest):
    """
    广播 Job 更新
    
    POST /api/v1/p2p/broadcast/job_update
    """
    from ..core.p2p import JobUpdate
    
    update = JobUpdate(
        job_id=request.job_id,
        status=request.status,
        node_id=request.node_id,
        match_id=request.match_id,
        result_hash=request.result_hash
    )
    
    await p2p_service.broadcast_job_update(update)
    
    return {
        "success": True,
        "message": "Job update broadcasted"
    }


@router.post("/broadcast/node_state")
async def broadcast_node_state(request: BroadcastNodeStateRequest):
    """
    广播节点状态
    
    POST /api/v1/p2p/broadcast/node_state
    """
    from ..core.p2p import NodeState
    
    state = NodeState(
        node_id=request.node_id,
        status=request.status,
        gpu_available=request.gpu_available,
        gpu_type=request.gpu_type,
        vram_gb=request.vram_gb,
        current_jobs=request.current_jobs
    )
    
    await p2p_service.broadcast_node_state(state)
    
    return {
        "success": True,
        "message": "Node state broadcasted"
    }


# ==================== 订阅端点 ====================

@router.get("/subscriptions")
async def list_subscriptions():
    """
    列出当前订阅
    
    GET /api/v1/p2p/subscriptions
    """
    return {
        "topics": ["job_update", "node_state"]
    }


# ==================== 指标端点 ====================

@router.get("/metrics")
async def get_p2p_metrics():
    """
    获取 P2P 指标
    
    GET /api/v1/p2p/metrics
    """
    return p2p_service.get_metrics()


@router.get("/health")
async def health_check():
    """
    健康检查
    
    GET /api/v1/p2p/health
    """
    status = p2p_service.get_status()
    return {
        "status": "healthy" if status["running"] else "stopped",
        "running": status["running"],
        "connected_peers": status["connected_peers"]
    }
