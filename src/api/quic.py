"""
F14: QUIC Transport - API 端点

推理请求与结果接口
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json

from ..core.quic import quic_service, QUICConfig, InferenceRequest

router = APIRouter(prefix="/api/v1/inference", tags=["inference"])


# ==================== 请求/响应模型 ====================

class ExecuteRequest(BaseModel):
    job_id: str
    match_id: str
    model: str
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = True
    timeout_ms: int = 30000


class ExecuteResponse(BaseModel):
    job_id: str
    session_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    job_id: str
    status: str
    tokens_received: int
    latency_ms: int
    result_hash: Optional[str] = None
    error: Optional[str] = None


class ResultResponse(BaseModel):
    job_id: str
    result_text: str
    result_hash: str
    tokens_count: int
    actual_latency_ms: int
    streaming_complete: bool
    error: Optional[str] = None


class MetricsResponse(BaseModel):
    active_sessions: int
    total_sessions: int
    completed_sessions: int
    failed_sessions: int
    avg_latency_ms: float
    p50_latency_ms: float
    p99_latency_ms: float


# ==================== 推理请求端点 ====================

@router.post("/execute", response_model=ExecuteResponse)
async def execute_inference(request: ExecuteRequest):
    """
    执行推理请求
    
    POST /api/v1/inference/execute
    
    发起一个新的推理任务
    """
    # 创建请求对象
    inf_request = InferenceRequest(
        job_id=request.job_id,
        match_id=request.match_id,
        model=request.model,
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        stream=request.stream,
        timeout_ms=request.timeout_ms
    )
    
    # 创建会话
    session = await quic_service.create_session(inf_request)
    
    # 模拟推理执行 (实际场景中会调用 Node Agent)
    asyncio.create_task(_execute_mock_inference(request.job_id, request.prompt, request.max_tokens, request.stream))
    
    return ExecuteResponse(
        job_id=request.job_id,
        session_id=session.job_id,
        status="started",
        message="Inference session created"
    )


async def _execute_mock_inference(job_id: str, prompt: str, max_tokens: int, stream: bool):
    """
    模拟推理执行
    
    实际场景中，这个逻辑会在 Node Agent 执行推理后被调用
    """
    # 启动推理
    await quic_service.start_inference(job_id)
    
    # 模拟 streaming tokens
    if stream:
        words = prompt.split()[:3]
        mock_tokens = [f"响应 {i}: {words[i % len(words)]}" for i in range(min(max_tokens, 10))]
        
        for token in mock_tokens:
            await asyncio.sleep(0.1)  # 模拟延迟
            await quic_service.add_streaming_token(job_id, token)
    
    # 完成推理
    await quic_service.complete_inference(job_id)


@router.get("/status/{job_id}", response_model=StatusResponse)
async def get_inference_status(job_id: str):
    """
    获取推理状态
    
    GET /api/v1/inference/status/{job_id}
    """
    status_info = await quic_service.get_status(job_id)
    
    if not status_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {job_id}"
        )
    
    return StatusResponse(**status_info)


@router.get("/result/{job_id}", response_model=ResultResponse)
async def get_inference_result(job_id: str):
    """
    获取推理结果
    
    GET /api/v1/inference/result/{job_id}
    """
    result = await quic_service.get_result(job_id)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Result not found: {job_id}"
        )
    
    return ResultResponse(
        job_id=result.job_id,
        result_text=result.result_text,
        result_hash=result.result_hash,
        tokens_count=result.tokens_count,
        actual_latency_ms=result.actual_latency_ms,
        streaming_complete=result.streaming_complete,
        error=result.error
    )


@router.get("/sessions")
async def list_sessions(status_filter: Optional[str] = None):
    """
    列出所有推理会话
    
    GET /api/v1/inference/sessions
    """
    sessions = await quic_service.get_all_sessions()
    
    result = []
    for session in sessions:
        if status_filter and session.status.value != status_filter:
            continue
        
        result.append({
            "job_id": session.job_id,
            "match_id": session.match_id,
            "model": session.request.model,
            "status": session.status.value,
            "tokens_count": session.tokens_count,
            "latency_ms": session.request.latency_ms,
            "created_at": session.created_at.isoformat()
        })
    
    return {"sessions": result, "total": len(result)}


@router.get("/active")
async def list_active_sessions():
    """
    列出活跃会话
    
    GET /api/v1/inference/active
    """
    sessions = await quic_service.get_active_sessions()
    
    return {
        "sessions": [
            {
                "job_id": s.job_id,
                "status": s.status.value,
                "tokens_count": s.tokens_count,
                "elapsed_ms": s.request.latency_ms
            }
            for s in sessions
        ],
        "count": len(sessions)
    }


@router.post("/cancel/{job_id}")
async def cancel_inference(job_id: str):
    """
    取消推理
    
    POST /api/v1/inference/cancel/{job_id}
    """
    session = await quic_service.get_session(job_id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {job_id}"
        )
    
    if session.is_complete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session already completed: {job_id}"
        )
    
    # 取消会话
    await quic_service.fail_inference(job_id, "Cancelled by user", "CANCELLED")
    
    return {"success": True, "job_id": job_id, "message": "Inference cancelled"}


# ==================== 指标端点 ====================

@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取推理指标
    
    GET /api/v1/inference/metrics
    """
    metrics = quic_service.get_metrics()
    return MetricsResponse(**metrics)


@router.get("/health")
async def health_check():
    """
    健康检查
    
    GET /api/v1/inference/health
    """
    return {
        "status": "healthy",
        "running": quic_service._running,
        "active_sessions": quic_service._metrics.active_sessions
    }


# ==================== 配置端点 ====================

@router.get("/config")
async def get_quic_config():
    """
    获取 QUIC 配置
    
    GET /api/v1/inference/config
    """
    return {
        "server_host": quic_service.config.server_host,
        "server_port": quic_service.config.server_port,
        "connection_timeout_ms": quic_service.config.connection_timeout_ms,
        "stream_timeout_ms": quic_service.config.stream_timeout_ms,
        "max_concurrent_streams": quic_service.config.max_concurrent_streams,
        "enable_0_rtt": quic_service.config.enable_0_rtt,
        "congestion_control": quic_service.config.congestion_control
    }
