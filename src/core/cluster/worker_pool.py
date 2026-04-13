"""
Worker Pool Service
F11: Worker Pool - 无状态 Worker 管理

高度依赖网络状态，与 Scaler 协同工作

网络冗余机制:
1. 多 Relay 节点候选
2. 心跳超时检测
3. 网络切换 (直连 ↔ Relay)
4. 离线降级模式
5. 自动重连
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# 默认心跳超时时间 (秒)
DEFAULT_HEARTBEAT_TIMEOUT_SEC = 60
# 自动重连间隔 (秒)
DEFAULT_RECONNECT_INTERVAL_SEC = 10


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
    connection_type: str = "unknown"  # direct, relayed, unknown
    
    # 冗余机制
    retry_count: int = 0
    max_retry_count: int = 5
    last_reconnect_attempt: Optional[datetime] = None
    network_failures: int = 0
    
    @property
    def endpoint(self) -> str:
        return f"http://{self.address}:{self.port}"
    
    @property
    def idle_time_sec(self) -> int:
        return (datetime.utcnow() - self.last_heartbeat).total_seconds()
    
    @property
    def heartbeat_timeout(self) -> bool:
        """心跳是否超时"""
        return self.idle_time_sec > DEFAULT_HEARTBEAT_TIMEOUT_SEC
    
    @property
    def is_available(self) -> bool:
        """Worker 是否可用 (状态正常 + 网络可达 + 未超时)"""
        return (
            self.status in ("ready", "busy") and 
            self.p2p_connected and 
            not self.heartbeat_timeout
        )
    
    @property
    def can_retry(self) -> bool:
        """是否可以重试"""
        return self.retry_count < self.max_retry_count


class WorkerPoolService:
    """
    Worker Pool 服务
    
    职责:
    1. Worker 注册与心跳
    2. 请求分发 (依赖网络状态)
    3. 平滑下线
    4. 状态同步
    
    网络冗余机制:
    - P2PService: Worker 网络连接状态
    - RelayService: Relay 兜底状态
    - ScalerService: 扩缩触发
    - 心跳超时检测
    - 自动重连
    """
    
    def __init__(self):
        self._workers: dict[str, Worker] = {}
        self._lock = asyncio.Lock()
        
        # 回调
        self._on_worker_create: Optional[Callable] = None
        self._on_worker_destroy: Optional[Callable] = None
        self._on_worker_scaled: Optional[Callable] = None
        self._on_worker_unavailable: Optional[Callable] = None
        
        # P2P 和 Relay 服务引用
        self._p2p_service = None
        self._relay_service = None
        self._scaler_service = None
        
        # 后台任务
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        
        # 配置
        self._heartbeat_timeout_sec = DEFAULT_HEARTBEAT_TIMEOUT_SEC
        self._reconnect_interval_sec = DEFAULT_RECONNECT_INTERVAL_SEC
        
        logger.info("WorkerPoolService initialized with network redundancy")
    
    def set_p2p_service(self, p2p_service):
        """设置 P2P 服务"""
        self._p2p_service = p2p_service
    
    def set_relay_service(self, relay_service):
        """设置 Relay 服务"""
        self._relay_service = relay_service
    
    def set_scaler_service(self, scaler_service):
        """设置 Scaler 服务"""
        self._scaler_service = scaler_service
    
    # ==================== 生命周期 ====================
    
    async def start(self):
        """启动 Worker Pool"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info("WorkerPool started with network redundancy")
    
    async def stop(self):
        """停止 Worker Pool"""
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()
        
        logger.info("WorkerPool stopped")
    
    # ==================== 后台任务 ====================
    
    async def _cleanup_loop(self):
        """
        清理循环
        
        检测心跳超时的 Worker 并标记为不可用
        """
        while self._running:
            try:
                await asyncio.sleep(10)  # 每 10 秒检查一次
                await self._check_heartbeat_timeout()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
    
    async def _check_heartbeat_timeout(self):
        """检查心跳超时"""
        async with self._lock:
            now = datetime.utcnow()
            timeout_workers = []
            
            for worker_id, worker in self._workers.items():
                if worker.status in ("ready", "busy"):
                    idle = (now - worker.last_heartbeat).total_seconds()
                    
                    if idle > self._heartbeat_timeout_sec:
                        # 标记为不可用，但不立即移除
                        if worker.p2p_connected:
                            logger.warning(
                                f"Worker {worker_id} heartbeat timeout: {idle:.1f}s"
                            )
                            worker.p2p_connected = False
                            worker.network_failures += 1
                            
                            # 触发不可用回调
                            if self._on_worker_unavailable:
                                try:
                                    await self._on_worker_unavailable(worker_id, "timeout")
                                except Exception as e:
                                    logger.error(f"Worker unavailable callback failed: {e}")
                        
                        # 连续超时次数过多，移除 Worker
                        if worker.network_failures >= 3:
                            timeout_workers.append(worker_id)
            
            # 移除连续超时的 Worker
            for worker_id in timeout_workers:
                del self._workers[worker_id]
                logger.error(f"Worker removed due to heartbeat timeout: {worker_id}")
    
    async def _reconnect_loop(self):
        """
        重连循环
        
        尝试重连不可用的 Worker
        """
        while self._running:
            try:
                await asyncio.sleep(self._reconnect_interval_sec)
                await self._try_reconnect_workers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reconnect loop error: {e}")
    
    async def _try_reconnect_workers(self):
        """尝试重连不可用的 Worker"""
        async with self._lock:
            for worker_id, worker in self._workers.items():
                if not worker.p2p_connected and worker.can_retry:
                    # 检查是否到了重连时间
                    if worker.last_reconnect_attempt:
                        elapsed = (
                            datetime.utcnow() - worker.last_reconnect_attempt
                        ).total_seconds()
                        if elapsed < self._reconnect_interval_sec:
                            continue
                    
                    # 尝试重连
                    worker.last_reconnect_attempt = datetime.utcnow()
                    worker.retry_count += 1
                    
                    logger.info(
                        f"Attempting to reconnect worker: {worker_id} "
                        f"(attempt {worker.retry_count}/{worker.max_retry_count})"
                    )
                    
                    # 尝试通过 Relay 重连
                    if self._relay_service:
                        try:
                            # 获取可用的 Relay 节点
                            relay_node = await self._relay_service.get_available_relay_node()
                            if relay_node:
                                # 通过 Relay 连接
                                await self._p2p_service.connect_peer(
                                    worker_id, 
                                    relay_node=relay_node.peer_id
                                )
                                worker.relay_node = relay_node.peer_id
                                worker.connection_type = "relayed"
                                logger.info(
                                    f"Worker {worker_id} reconnected via relay: "
                                    f"{relay_node.peer_id[:12]}"
                                )
                        except Exception as e:
                            logger.error(f"Relay reconnect failed: {e}")
                    
                    # 如果 Relay 也失败，尝试直连
                    if not worker.p2p_connected:
                        try:
                            await self._p2p_service.connect_peer(worker_id)
                            worker.connection_type = "direct"
                            logger.info(f"Worker {worker_id} reconnected directly")
                        except Exception as e:
                            logger.error(f"Direct reconnect failed: {e}")
                    
                    # 更新连接状态
                    if worker.p2p_connected:
                        worker.retry_count = 0
                        worker.network_failures = 0
    
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
                    # 尝试直连
                    connected = await self._p2p_service.connect_peer(worker_id)
                    
                    if connected:
                        worker.p2p_connected = True
                        worker.connection_type = "direct"
                        logger.info(f"Worker registered to P2P (direct): {worker_id}")
                    else:
                        # 直连失败，尝试 Relay
                        if self._relay_service:
                            relay_node = await self._relay_service.get_available_relay_node()
                            if relay_node:
                                connected = await self._p2p_service.connect_peer(
                                    worker_id,
                                    relay_node=relay_node.peer_id
                                )
                                if connected:
                                    worker.p2p_connected = True
                                    worker.relay_node = relay_node.peer_id
                                    worker.connection_type = "relayed"
                                    logger.info(
                                        f"Worker registered to P2P (relayed): {worker_id} "
                                        f"via {relay_node.peer_id[:12]}"
                                    )
                except Exception as e:
                    logger.error(f"Failed to register worker to P2P: {e}")
            
            return worker
    
    async def heartbeat(self, worker_id: str, status: str = "ready",
                       current_requests: int = 0) -> bool:
        """
        Worker 心跳
        
        同时更新网络状态和重置超时计数
        """
        async with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                logger.warning(f"Heartbeat from unknown worker: {worker_id}")
                return False
            
            worker.last_heartbeat = datetime.utcnow()
            worker.status = status
            worker.current_requests = current_requests
            
            # 如果之前不可用，现在恢复，重置计数
            if not worker.p2p_connected:
                worker.p2p_connected = True
                worker.retry_count = 0
                worker.network_failures = 0
                logger.info(f"Worker {worker_id} recovered from network failure")
            
            # 更新网络诊断
            if self._relay_service:
                try:
                    diagnostics = await self._relay_service.diagnose_connection(worker_id)
                    if diagnostics:
                        worker.relay_node = diagnostics.get("relay_node")
                        worker.connection_type = diagnostics.get("connection_type", "unknown")
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
    
    async def get_unavailable_workers(self) -> List[Worker]:
        """获取不可用的 Worker (网络不可达)"""
        return [w for w in self._workers.values() if not w.p2p_connected]
    
    async def remove_worker(self, worker_id: str) -> bool:
        """移除 Worker"""
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
            
            # 再试一次
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
            
            if not worker.is_available:
                logger.warning(f"Worker not available: {worker_id}")
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
        """平滑下线 Worker"""
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
                    
                    if self._p2p_service:
                        try:
                            await self._p2p_service.disconnect_peer(worker_id)
                        except:
                            pass
                    
                    del self._workers[worker_id]
                    return True
    
    # ==================== Scaler 协同 ====================
    
    async def create_worker_for_scaler(self) -> Optional[str]:
        """为 Scaler 创建 Worker"""
        worker_id = f"worker-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{len(self._workers)}"
        
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
        """为 Scaler 销毁 Worker"""
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
            "via_direct": sum(1 for w in workers if w.connection_type == "direct"),
            "via_relay": sum(1 for w in workers if w.connection_type == "relayed"),
            "unavailable": sum(1 for w in workers if not w.p2p_connected),
            "retrying": sum(1 for w in workers if w.retry_count > 0),
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
                "connection_type": w.connection_type,
                "relay_node": w.relay_node,
                "is_available": w.is_available,
                "retry_count": w.retry_count,
                "network_failures": w.network_failures,
            }
            for w in self._workers.values()
        ]


# ==================== 单例 ====================

worker_pool_service = WorkerPoolService()
