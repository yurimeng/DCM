"""
Worker Pool Service
F11: Worker Pool - 无状态 Worker 管理

高度依赖网络状态，与 Scaler 协同工作

集成:
- P2PService: Worker 网络连接
- RelayService: Relay 兜底
- ScalerService: 扩缩协同
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Callable
from dataclasses import dataclass, field

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
    
    # 网络状态
    p2p_connected: bool = False
    relay_node: Optional[str] = None
    
    @property
    def endpoint(self) -> str:
        return f"http://{self.address}:{self.port}"
    
    @property
    def idle_time_sec(self) -> int:
        return (datetime.utcnow() - self.last_heartbeat).total_seconds()
    
    @property
    def is_available(self) -> bool:
        """Worker 是否可用"""
        return self.status in ("ready", "busy") and self.p2p_connected


class WorkerPoolService:
    """
    Worker Pool 服务
    
    职责:
    1. Worker 注册与心跳
    2. 请求分发 (依赖网络状态)
    3. 平滑下线
    4. 状态同步
    
    集成:
    - P2PService: Worker 网络连接状态
    - RelayService: Relay 兜底状态
    - ScalerService: 扩缩触发
    """
    
    def __init__(self):
        self._workers: dict[str, Worker] = {}
        self._lock = asyncio.Lock()
        
        # 回调
        self._on_worker_create: Optional[Callable] = None
        self._on_worker_destroy: Optional[Callable] = None
        self._on_worker_scaled: Optional[Callable] = None
        
        # P2P 和 Relay 服务引用 (由外部设置)
        self._p2p_service = None
        self._relay_service = None
        self._scaler_service = None
        
        logger.info("WorkerPoolService initialized")
    
    def set_p2p_service(self, p2p_service):
        """设置 P2P 服务"""
        self._p2p_service = p2p_service
    
    def set_relay_service(self, relay_service):
        """设置 Relay 服务"""
        self._relay_service = relay_service
    
    def set_scaler_service(self, scaler_service):
        """设置 Scaler 服务"""
        self._scaler_service = scaler_service
    
    # ==================== Worker 管理 ====================
    
    async def register_worker(self, worker_id: str, address: str, 
                              port: int = 8000) -> Worker:
        """
        注册新 Worker
        
        同时注册到 P2P 网络
        """
        async with self._lock:
            worker = Worker(
                worker_id=worker_id,
                address=address,
                port=port,
                status="creating"
            )
            self._workers[worker_id] = worker
            logger.info(f"Worker registered: {worker_id}")
            
            # 注册到 P2P 网络
            if self._p2p_service:
                try:
                    await self._p2p_service.add_peer(
                        peer_id=worker_id,
                        addresses=[f"/ip4/{address}/tcp/{port}"],
                        is_relay=False
                    )
                    worker.p2p_connected = True
                    logger.info(f"Worker registered to P2P: {worker_id}")
                except Exception as e:
                    logger.error(f"Failed to register worker to P2P: {e}")
            
            return worker
    
    async def heartbeat(self, worker_id: str, status: str = "ready",
                       current_requests: int = 0) -> bool:
        """
        Worker 心跳
        
        同时更新网络状态
        """
        async with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                logger.warning(f"Heartbeat from unknown worker: {worker_id}")
                return False
            
            worker.last_heartbeat = datetime.utcnow()
            worker.status = status
            worker.current_requests = current_requests
            
            # 检查网络状态
            if self._relay_service:
                try:
                    diagnostics = await self._relay_service.diagnose_connection(worker_id)
                    if diagnostics:
                        worker.relay_node = diagnostics.get("relay_node")
                        worker.p2p_connected = diagnostics.get("connection_type") != "unknown"
                except Exception as e:
                    logger.debug(f"Network diagnostics failed: {e}")
            
            return True
    
    async def get_worker(self, worker_id: str) -> Optional[Worker]:
        """获取 Worker"""
        return self._workers.get(worker_id)
    
    async def get_all_workers(self) -> List[Worker]:
        """获取所有 Worker"""
        return list(self._workers.values())
    
    async def get_ready_workers(self) -> List[Worker]:
        """获取就绪的 Worker (只返回网络可达的)"""
        return [w for w in self._workers.values() 
                if w.is_available]
    
    async def get_available_workers(self) -> List[Worker]:
        """获取可用的 Worker (网络可达)"""
        return [w for w in self._workers.values() if w.p2p_connected]
    
    async def remove_worker(self, worker_id: str) -> bool:
        """
        移除 Worker
        
        同时从 P2P 网络移除
        """
        async with self._lock:
            if worker_id in self._workers:
                worker = self._workers[worker_id]
                
                # 从 P2P 网络移除
                if self._p2p_service:
                    try:
                        await self._p2p_service.disconnect_peer(worker_id)
                    except Exception as e:
                        logger.error(f"Failed to disconnect worker from P2P: {e}")
                
                del self._workers[worker_id]
                logger.info(f"Worker removed: {worker_id}")
                return True
            return False
    
    # ==================== 请求分发 ====================
    
    async def select_worker(self) -> Optional[Worker]:
        """
        选择 Worker (最少连接优先)
        
        只选择网络可达的 Worker
        """
        ready_workers = await self.get_ready_workers()
        
        if not ready_workers:
            # 如果没有就绪的，尝试触发 Scaler 扩容
            if self._scaler_service:
                logger.info("No ready workers, triggering scale up")
                await self._scaler_service.scale_up(1)
            
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
            
            if not worker.is_available:
                logger.warning(f"Worker not available: {worker_id}")
                return False
            
            worker.current_requests += 1
            worker.status = "busy"
            
            # 通知 Scaler 有新请求
            if self._scaler_service:
                # 可以记录请求增加，用于扩缩决策
                pass
            
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
        5. 从 P2P 网络移除
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
                    
                    # 从 P2P 网络移除
                    if self._p2p_service:
                        try:
                            await self._p2p_service.disconnect_peer(worker_id)
                        except Exception as e:
                            logger.error(f"Failed to disconnect worker: {e}")
                    
                    # 移除
                    del self._workers[worker_id]
                    logger.info(f"Worker stopped: {worker_id}")
                    
                    # 通知 Scaler Worker 已下线
                    if self._scaler_service:
                        logger.info(f"Worker {worker_id} stopped, updating scaler")
                    
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
                    
                    if self._p2p_service:
                        try:
                            await self._p2p_service.disconnect_peer(worker_id)
                        except:
                            pass
                    
                    del self._workers[worker_id]
                    return True
    
    # ==================== Scaler 协同 ====================
    
    async def create_worker_for_scaler(self) -> Optional[str]:
        """
        为 Scaler 创建 Worker
        
        Returns:
            Worker ID 或 None
        """
        worker_id = f"worker-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{len(self._workers)}"
        
        # 获取可用地址 (这里简化处理，实际应该从 Core 节点列表选择)
        if self._p2p_service:
            try:
                status = self._p2p_service.get_status()
                peer_id = status.get("peer_id")
                if peer_id:
                    worker = await self.register_worker(
                        worker_id=worker_id,
                        address="127.0.0.1",
                        port=8000
                    )
                    return worker_id
            except Exception as e:
                logger.error(f"Failed to create worker: {e}")
        
        return None
    
    async def destroy_worker_for_scaler(self, worker_id: str):
        """
        为 Scaler 销毁 Worker
        """
        await self.drain_worker(worker_id)
    
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
        
        # 网络状态统计
        network_stats = {
            "p2p_connected": sum(1 for w in workers if w.p2p_connected),
            "via_relay": sum(1 for w in workers if w.relay_node),
            "unavailable": sum(1 for w in workers if not w.p2p_connected),
        }
        
        return {
            "total_workers": len(workers),
            "by_status": by_status,
            "network_stats": network_stats,
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
                "endpoint": w.endpoint,
                "created_at": w.created_at.isoformat(),
                "idle_time_sec": w.idle_time_sec,
                "current_requests": w.current_requests,
                "completed_requests": w.completed_requests,
                "p2p_connected": w.p2p_connected,
                "relay_node": w.relay_node,
                "is_available": w.is_available,
            }
            for w in self._workers.values()
        ]


# ==================== 单例 ====================

worker_pool_service = WorkerPoolService()
