"""
F10: Scaler - API 端点

自动扩缩容管理接口
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List

from ..core.cluster import scaler_service, ScalerService, ScalingConfig, ScalingMetrics, ScalingThresholds

router = APIRouter(prefix="/api/v1/scaler", tags=["scaler"])


# ==================== 请求/响应模型 ====================

class ScaleRequest(BaseModel):
    workers: int


class ScaleResponse(BaseModel):
    requested: int
    current: int
    pending: int


class MetricsResponse(BaseModel):
    cpu_usage: float
    memory_usage: float
    queue_length: int
    latency_p99_ms: float
    error_rate: float
    active_workers: int
    pending_workers: int
    timestamp: str


class StatusResponse(BaseModel):
    mode: str
    min_workers: int
    max_workers: int
    current_workers: int
    scale_up_cooldown: int
    scale_down_cooldown: int
    last_scale_up: Optional[str]
    last_scale_down: Optional[str]


class WorkerResponse(BaseModel):
    worker_id: str
    status: str
    created_at: str
    idle_time_sec: int
    current_requests: int
    completed_requests: int


class WorkerListResponse(BaseModel):
    workers: List[WorkerResponse]
    total: int


class ThresholdsResponse(BaseModel):
    cpu_scale_up: float
    queue_scale_up: int
    latency_scale_up: float
    error_rate_scale_up: float
    scale_up_duration_sec: int
    cpu_scale_down: float
    queue_scale_down: int
    worker_idle_sec: int
    scale_down_cooldown_sec: int


# ==================== 指标端点 ====================

@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取扩缩指标
    
    GET /api/v1/scaler/metrics
    """
    metrics = scaler_service.get_current_metrics()
    
    if not metrics:
        metrics = ScalingMetrics()
    
    return MetricsResponse(
        cpu_usage=metrics.cpu_usage,
        memory_usage=metrics.memory_usage,
        queue_length=metrics.queue_length,
        latency_p99_ms=metrics.latency_p99_ms,
        error_rate=metrics.error_rate,
        active_workers=metrics.active_workers,
        pending_workers=metrics.pending_workers,
        timestamp=metrics.timestamp.isoformat()
    )


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """
    获取扩缩状态
    
    GET /api/v1/scaler/status
    """
    status_info = scaler_service.get_status()
    
    return StatusResponse(
        mode=status_info["mode"],
        min_workers=status_info["min_workers"],
        max_workers=status_info["max_workers"],
        current_workers=status_info["current_workers"],
        scale_up_cooldown=0,
        scale_down_cooldown=0,
        last_scale_up=status_info.get("last_scale_up"),
        last_scale_down=status_info.get("last_scale_down")
    )


# ==================== 扩缩端点 ====================

@router.post("/scale", response_model=ScaleResponse)
async def manual_scale(request: ScaleRequest):
    """
    手动扩缩
    
    POST /api/v1/scaler/scale
    """
    current = len(scaler_service._workers)
    requested = request.workers
    
    if requested < scaler_service.config.min_workers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested workers ({requested}) less than min_workers ({scaler_service.config.min_workers})"
        )
    
    if requested > scaler_service.config.max_workers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Requested workers ({requested}) exceeds max_workers ({scaler_service.config.max_workers})"
        )
    
    if requested > current:
        # 扩容
        await scaler_service.scale_up(requested - current)
    elif requested < current:
        # 缩容
        await scaler_service.scale_down(current - requested)
    
    return ScaleResponse(
        requested=requested,
        current=len(scaler_service._workers),
        pending=0
    )


@router.post("/scale/up")
async def scale_up(workers: int = 1):
    """
    扩容
    
    POST /api/v1/scaler/scale/up
    """
    if workers < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workers must be >= 1"
        )
    
    current = len(scaler_service._workers)
    if current + workers > scaler_service.config.max_workers:
        workers = scaler_service.config.max_workers - current
    
    if workers > 0:
        await scaler_service.scale_up(workers)
    
    return {
        "success": True,
        "workers_added": workers,
        "current_workers": len(scaler_service._workers)
    }


@router.post("/scale/down")
async def scale_down(workers: int = 1):
    """
    缩容
    
    POST /api/v1/scaler/scale/down
    """
    if workers < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workers must be >= 1"
        )
    
    removed = await scaler_service.scale_down(workers)
    
    return {
        "success": True,
        "workers_removed": len(removed),
        "current_workers": len(scaler_service._workers)
    }


# ==================== Worker 管理端点 ====================

@router.get("/workers", response_model=WorkerListResponse)
async def list_workers():
    """
    列出所有 Worker
    
    GET /api/v1/scaler/workers
    """
    workers = scaler_service.get_workers()
    
    return WorkerListResponse(
        workers=[WorkerResponse(**w) for w in workers],
        total=len(workers)
    )


@router.get("/workers/{worker_id}")
async def get_worker(worker_id: str):
    """
    获取 Worker 详情
    
    GET /api/v1/scaler/workers/{worker_id}
    """
    workers = scaler_service.get_workers()
    
    for w in workers:
        if w["worker_id"] == worker_id:
            return w
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Worker not found: {worker_id}"
    )


# ==================== 配置端点 ====================

@router.get("/config")
async def get_config():
    """
    获取配置
    
    GET /api/v1/scaler/config
    """
    return {
        "enabled": scaler_service.config.enabled,
        "min_workers": scaler_service.config.min_workers,
        "max_workers": scaler_service.config.max_workers,
        "check_interval_sec": scaler_service.config.check_interval_sec
    }


@router.get("/thresholds", response_model=ThresholdsResponse)
async def get_thresholds():
    """
    获取扩缩阈值
    
    GET /api/v1/scaler/thresholds
    """
    t = scaler_service.config.thresholds
    
    return ThresholdsResponse(
        cpu_scale_up=t.cpu_scale_up,
        queue_scale_up=t.queue_scale_up,
        latency_scale_up=t.latency_scale_up,
        error_rate_scale_up=t.error_rate_scale_up,
        scale_up_duration_sec=t.scale_up_duration_sec,
        cpu_scale_down=t.cpu_scale_down,
        queue_scale_down=t.queue_scale_down,
        worker_idle_sec=t.worker_idle_sec,
        scale_down_cooldown_sec=t.scale_down_cooldown_sec
    )


@router.post("/thresholds")
async def update_thresholds(thresholds: ThresholdsResponse):
    """
    更新扩缩阈值
    
    POST /api/v1/scaler/thresholds
    """
    scaler_service.config.thresholds = ScalingThresholds(
        cpu_scale_up=thresholds.cpu_scale_up,
        queue_scale_up=thresholds.queue_scale_up,
        latency_scale_up=thresholds.latency_scale_up,
        error_rate_scale_up=thresholds.error_rate_scale_up,
        scale_up_duration_sec=thresholds.scale_up_duration_sec,
        cpu_scale_down=thresholds.cpu_scale_down,
        queue_scale_down=thresholds.queue_scale_down,
        worker_idle_sec=thresholds.worker_idle_sec,
        scale_down_cooldown_sec=thresholds.scale_down_cooldown_sec
    )
    
    return {"success": True, "message": "Thresholds updated"}


# ==================== 健康检查端点 ====================

@router.get("/health")
async def health_check():
    """
    健康检查
    
    GET /api/v1/scaler/health
    """
    status_info = scaler_service.get_status()
    
    return {
        "status": "healthy",
        "enabled": status_info["enabled"],
        "current_workers": status_info["current_workers"]
    }
