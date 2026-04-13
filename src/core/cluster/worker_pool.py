"""
Worker Pool Service
F11: Worker Pool - 无状态 Worker 管理
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Callable
from dataclasses import dataclass, field

from .models import CoreNode

logger = logging.getLogger(__name__)


@dataclass
class Worker:
    """Worker 信息"""
    worker_id: str
    address: str
    port: int = 8000
    status: str = "creating"  # creating, ready, busy, draining, stopped
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    current_requests: int = 0
    completed_requests: int = 0
    
    @property
    def endpoint(self) -> str:
        return f"http://{self.address}:{self.port}"
    
    @property
    def idle_time_sec(self) -> int:
        return (datetime.utcnow() - self.last_heartbeat).total_seconds()


class WorkerPoolService:
    """
    Worker Pool 服务
    
    职责:
    1. Worker 注册与心跳
    2. 请求分发
    3. 平滑下线
    4. 状态同步
    """
    
    def __init__(self):
        self._workers: dict[str, Worker] = {}
        self._lock = asyncio.Lock()
        
        # 回调
        self._on_worker_create: Optional[Callable] = None
        self._on_worker_destroy: Optional[Callable] = None
        
        logger.info("WorkerPoolService initialized")
    
    # ==================== Worker 管理 ====================
    
    async def register_worker(self, worker_id: str, address: str, 
                              port: int = 8000) -> Worker:
        """注册新 Worker"""
        async with self._lock:
            worker = Worker(
                worker_id=worker_id,
                address=address,
                port=port,
                status="creating"
            )
            self._workers[worker_id] = worker
            logger.info(f"Worker registered: {worker_id}")
            return worker
    
    async def heartbeat(self, worker_id: str, status: str = "ready",
                       current_requests: int = 0) -> bool:
        """Worker 心跳"""
        async with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                logger.warning(f"Heartbeat from unknown worker: {worker_id}")
                return False
            
            worker.last_heartbeat = datetime.utcnow()
            worker.status = status
            worker.current_requests = current_requests
            return True
    
    async def get_worker(self, worker_id: str) -> Optional[Worker]:
        """获取 Worker"""
        return self._workers.get(worker_id)
    
    async def get_all_workers(self) -> List[Worker]:
        """获取所有 Worker"""
        return list(self._workers.values())
    
    async def get_ready_workers(self) -> List[Worker]:
        """获取就绪的 Worker"""
        return [w for w in self._workers.values() 
                if w.status in ("ready", "busy")]
    
    async def remove_worker(self, worker_id: str) -> bool:
        """移除 Worker"""
        async with self._lock:
            if worker_id in self._workers:
                del self._workers[worker_id]
                logger.info(f"Worker removed: {worker_id}")
                return True
            return False
    
    # ==================== 请求分发 ====================
    
    async def select_worker(self) -> Optional[Worker]:
        """
        选择 Worker（最少连接优先）
        """
        ready_workers = await self.get_ready_workers()
        
        if not ready_workers:
            logger.warning("No ready workers available")
            return None
        
        # 最少连接优先
        return min(ready_workers, key=lambda w: w.current_requests)
    
    async def dispatch_request(self, worker_id: str) -> bool:
        """分发请求到 Worker"""
        async with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                return False
            
            worker.current_requests += 1
            worker.status = "busy"
            return True
    
    async def complete_request(self, worker_id: str) -> bool:
        """请求完成"""
        async with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                return False
            
            worker.current_requests = max(0, worker.current_requests - 1)
            worker.completed_requests += 1
            
            if worker.current_requests == 0:
                worker.status = "ready"
            
            return True
    
    # ==================== 平滑下线 ====================
    
    async def drain_worker(self, worker_id: str) -> bool:
        """
        平滑下线 Worker
        
        流程:
        1. 标记为 draining
        2. 停止接受新请求
        3. 等待现有请求完成
        4. 调用销毁回调
        """
        async with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                return False
            
            worker.status = "draining"
            logger.info(f"Worker draining: {worker_id}, pending: {worker.current_requests}")
        
        # 等待请求完成
        while True:
            await asyncio.sleep(1)
            
            async with self._lock:
                worker = self._workers.get(worker_id)
                if not worker:
                    return True
                
                if worker.current_requests == 0:
                    # 调用销毁回调
                    if self._on_worker_destroy:
                        try:
                            await self._on_worker_destroy(worker_id)
                        except Exception as e:
                            logger.error(f"Worker destroy callback failed: {e}")
                    
                    # 移除
                    del self._workers[worker_id]
                    logger.info(f"Worker stopped: {worker_id}")
                    return True
                
                # 超时 60s 强制销毁
                elapsed = (datetime.utcnow() - worker.created_at).total_seconds()
                if elapsed > 60:
                    logger.warning(f"Worker force stopped: {worker_id}")
                    if self._on_worker_destroy:
                        try:
                            await self._on_worker_destroy(worker_id)
                        except:
                            pass
                    del self._workers[worker_id]
                    return True
    
    # ==================== 状态查询 ====================
    
    def get_status(self) -> dict:
        """获取 Worker Pool 状态"""
        workers = list(self._workers.values())
        
        by_status = {
            "creating": sum(1 for w in workers if w.status == "creating"),
            "ready": sum(1 for w in workers if w.status == "ready"),
            "busy": sum(1 for w in workers if w.status == "busy"),
            "draining": sum(1 for w in workers if w.status == "draining"),
        }
        
        return {
            "total_workers": len(workers),
            "by_status": by_status,
            "total_requests": sum(w.current_requests for w in workers),
            "total_completed": sum(w.completed_requests for w in workers),
        }
    
    def get_workers(self) -> List[dict]:
        """获取所有 Worker 详情"""
        return [
            {
                "worker_id": w.worker_id,
                "address": w.address,
                "port": w.port,
                "status": w.status,
                "created_at": w.created_at.isoformat(),
                "idle_time_sec": w.idle_time_sec,
                "current_requests": w.current_requests,
                "completed_requests": w.completed_requests,
            }
            for w in self._workers.values()
        ]


# ==================== 单例 ====================

worker_pool_service = WorkerPoolService()
