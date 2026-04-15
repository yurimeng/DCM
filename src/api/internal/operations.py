"""
Internal API - 运维接口
包含: 健康检查、配置获取
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any

router = APIRouter(prefix="", tags=["internal/operations"])


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    mvp_mode: bool
    services: Dict[str, Any]


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查端点

    GET /internal/v1/health

    用于 Render 健康检查
    """
    from ...services import matching_service
    from ...services.node_status_store import list_online_nodes

    # 获取在线节点数量
    online_nodes = list_online_nodes(max_age_seconds=10)

    # 获取待处理 Job 数量
    pending_jobs = 0
    if hasattr(matching_service, 'get_pending_jobs_count'):
        pending_jobs = matching_service.get_pending_jobs_count()

    # 获取队列状态
    queue_stats = {}
    if hasattr(matching_service, 'get_queue_stats'):
        queue_stats = matching_service.get_queue_stats()

    return HealthResponse(
        status="healthy",
        version="0.1.0",
        mvp_mode=True,
        services={
            "matching": "running",
            "online_nodes": len(online_nodes),
            "pending_jobs": pending_jobs,
            "queue": queue_stats,
        }
    )


@router.get("/config/job")
async def get_job_config():
    """
    获取 Job 配置
    
    GET /internal/v1/config/job
    
    返回当前 Job 配置（从 job_config 读取）
    """
    from ...services.job_config import get_job_config
    
    config = get_job_config()
    return {
        "max_output_tokens": config.max_output_tokens,
        "max_input_tokens": config.max_input_tokens,
        "max_latency_ms": config.max_latency_ms,
        "min_latency_ms": config.min_latency_ms,
        "default_output_tokens": config.default_output_tokens,
        "max_bid_price": config.max_bid_price,
        "min_bid_price": config.min_bid_price,
        "max_retries": config.max_retries,
    }


@router.post("/config/job/reload")
async def reload_job_config_endpoint():
    """
    重新加载 Job 配置
    
    POST /internal/v1/config/job/reload
    
    从环境变量重新加载配置
    """
    from ...services.job_config import reload_job_config
    
    config = reload_job_config()
    return {
        "status": "reloaded",
        "config": {
            "max_output_tokens": config.max_output_tokens,
            "max_input_tokens": config.max_input_tokens,
            "max_latency_ms": config.max_latency_ms,
            "min_latency_ms": config.min_latency_ms,
            "default_output_tokens": config.default_output_tokens,
            "max_bid_price": config.max_bid_price,
            "min_bid_price": config.min_bid_price,
            "max_retries": config.max_retries,
        }
    }


@router.get("/runtimes")
async def get_runtimes():
    """
    获取支持的运行时列表
    GET /internal/v1/runtimes
    Node Agent 可以调用此接口获取运行时配置
    """
    import yaml
    try:
        with open("config/models.yaml", "r") as f:
            config = yaml.safe_load(f)
        runtimes = config.get("runtimes", {})
        return {"runtimes": runtimes, "default": "ollama"}
    except Exception:
        return {
            "runtimes": {
                "ollama": {"endpoint": "http://localhost:11434", "timeout": 60, "api_format": "ollama"},
                "vllm": {"endpoint": "http://localhost:8000/v1", "timeout": 60, "api_format": "openai"},
            },
            "default": "ollama",
        }
