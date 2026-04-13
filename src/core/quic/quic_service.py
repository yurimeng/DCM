"""
F14: QUIC Transport - QUIC 服务

推理数据的可靠传输层
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Dict, Optional, Callable, List

from .models import (
    InferenceRequest, InferenceResult, InferenceSession,
    InferenceStatus, QUICConfig, QUICMetrics
)

logger = logging.getLogger(__name__)


class QUICService:
    """
    QUIC Transport 服务
    
    职责:
    1. 推理请求管理与执行
    2. Streaming 结果收集
    3. result_hash 计算
    4. 与 F5 验证服务集成
    """
    
    def __init__(self, config: Optional[QUICConfig] = None):
        self.config = config or QUICConfig()
        self._sessions: Dict[str, InferenceSession] = {}
        self._lock = asyncio.Lock()
        
        # 回调
        self._on_result_ready: Optional[Callable] = None  # 结果准备好时调用
        
        # 指标
        self._metrics = QUICMetrics()
        
        # 延迟统计 (ms)
        self._latencies: List[int] = []
        
        # 状态
        self._running = False
        
        logger.info(f"QUICService initialized, port={self.config.server_port}")
    
    # ==================== 生命周期 ====================
    
    async def start(self):
        """启动 QUIC 服务"""
        self._running = True
        logger.info("QUIC service started")
    
    async def stop(self):
        """停止 QUIC 服务"""
        self._running = False
        self._sessions.clear()
        logger.info("QUIC service stopped")
    
    # ==================== 推理请求 ====================
    
    async def create_session(self, request: InferenceRequest) -> InferenceSession:
        """创建推理会话"""
        async with self._lock:
            session = InferenceSession(
                job_id=request.job_id,
                match_id=request.match_id,
                request=request,
                status=InferenceStatus.PENDING
            )
            self._sessions[request.job_id] = session
            self._metrics.total_sessions += 1
            self._metrics.active_sessions += 1
            
            logger.info(f"Session created: job_id={request.job_id}")
            return session
    
    async def get_session(self, job_id: str) -> Optional[InferenceSession]:
        """获取推理会话"""
        return self._sessions.get(job_id)
    
    async def start_inference(self, job_id: str) -> bool:
        """开始推理"""
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                logger.warning(f"Session not found: {job_id}")
                return False
            
            session.status = InferenceStatus.RUNNING
            session.started_at = datetime.utcnow()
            session.request.start()
            
            logger.info(f"Inference started: job_id={job_id}")
            return True
    
    async def add_streaming_token(self, job_id: str, token: str) -> bool:
        """添加 streaming token"""
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                return False
            
            session.add_token(token)
            session.status = InferenceStatus.STREAMING
            
            return True
    
    async def complete_inference(self, job_id: str, error: Optional[str] = None) -> Optional[InferenceResult]:
        """完成推理"""
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                return None
            
            # 计算延迟
            latency_ms = session.request.latency_ms
            
            # 计算 result_hash
            result_text = session.result_text
            result_hash = hashlib.sha256(result_text.encode()).hexdigest()
            
            # 创建结果
            result = InferenceResult(
                job_id=job_id,
                result_text=result_text[:500],  # 限制长度
                result_hash=result_hash,
                tokens_count=session.tokens_count,
                actual_latency_ms=latency_ms,
                streaming_complete=True,
                error=error
            )
            
            session.result = result
            session.status = InferenceStatus.COMPLETED if not error else InferenceStatus.FAILED
            session.completed_at = datetime.utcnow()
            session.request.complete()
            
            # 更新指标
            self._metrics.completed_sessions += 1
            self._metrics.active_sessions -= 1
            self._metrics.tokens_processed += session.tokens_count
            self._latencies.append(latency_ms)
            self._update_latency_stats()
            
            logger.info(f"Inference completed: job_id={job_id}, tokens={session.tokens_count}, latency={latency_ms}ms")
            
            # 调用回调
            if self._on_result_ready:
                await self._on_result_ready(job_id, result)
            
            return result
    
    async def fail_inference(self, job_id: str, error: str, error_code: Optional[str] = None) -> Optional[InferenceResult]:
        """推理失败"""
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                return None
            
            result = InferenceResult(
                job_id=job_id,
                result_hash="",
                actual_latency_ms=session.request.latency_ms,
                streaming_complete=False,
                error=error,
                error_code=error_code
            )
            
            session.result = result
            session.status = InferenceStatus.FAILED
            session.completed_at = datetime.utcnow()
            
            self._metrics.failed_sessions += 1
            self._metrics.active_sessions -= 1
            
            logger.error(f"Inference failed: job_id={job_id}, error={error}")
            
            return result
    
    # ==================== 结果查询 ====================
    
    async def get_result(self, job_id: str) -> Optional[InferenceResult]:
        """获取推理结果"""
        session = self._sessions.get(job_id)
        return session.result if session else None
    
    async def get_status(self, job_id: str) -> Optional[dict]:
        """获取推理状态"""
        session = self._sessions.get(job_id)
        if not session:
            return None
        
        return {
            "job_id": job_id,
            "status": session.status.value,
            "tokens_received": session.tokens_count,
            "latency_ms": session.request.latency_ms,
            "result_hash": session.result.result_hash if session.result else None,
            "error": session.result.error if session.result else None
        }
    
    # ==================== 批量操作 ====================
    
    async def get_all_sessions(self) -> List[InferenceSession]:
        """获取所有会话"""
        return list(self._sessions.values())
    
    async def get_active_sessions(self) -> List[InferenceSession]:
        """获取活跃会话"""
        return [s for s in self._sessions.values() 
                if not s.is_complete]
    
    async def cleanup_completed(self, max_age_seconds: int = 3600):
        """清理已完成的会话"""
        async with self._lock:
            now = datetime.utcnow()
            to_remove = []
            
            for job_id, session in self._sessions.items():
                if session.is_complete and session.completed_at:
                    age = (now - session.completed_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(job_id)
            
            for job_id in to_remove:
                del self._sessions[job_id]
            
            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} completed sessions")
    
    # ==================== 指标统计 ====================
    
    def _update_latency_stats(self):
        """更新延迟统计"""
        if not self._latencies:
            return
        
        sorted_latencies = sorted(self._latencies)
        count = len(sorted_latencies)
        
        self._metrics.avg_latency_ms = sum(sorted_latencies) / count
        self._metrics.p50_latency_ms = sorted_latencies[int(count * 0.5)]
        self._metrics.p99_latency_ms = sorted_latencies[int(count * 0.99)] if count > 20 else sorted_latencies[-1]
    
    def get_metrics(self) -> dict:
        """获取 QUIC 指标"""
        return {
            "active_sessions": self._metrics.active_sessions,
            "total_sessions": self._metrics.total_sessions,
            "completed_sessions": self._metrics.completed_sessions,
            "failed_sessions": self._metrics.failed_sessions,
            "avg_latency_ms": round(self._metrics.avg_latency_ms, 2),
            "p50_latency_ms": round(self._metrics.p50_latency_ms, 2),
            "p99_latency_ms": round(self._metrics.p99_latency_ms, 2),
            "tokens_processed": self._metrics.tokens_processed,
            "bytes_transferred": self._metrics.bytes_transferred,
            "connections_established": self._metrics.connections_established,
            "connections_failed": self._metrics.connections_failed
        }
    
    def get_status(self) -> dict:
        """获取服务状态"""
        return {
            "running": self._running,
            "port": self.config.server_port,
            "sessions_count": len(self._sessions),
            "active_sessions": self._metrics.active_sessions,
            "metrics": self.get_metrics()
        }
    
    # ==================== 配置 ====================
    
    def set_result_callback(self, callback: Callable):
        """设置结果回调"""
        self._on_result_ready = callback


# ==================== 单例 ====================

quic_service = QUICService()
