"""
Matching Service - F3: 撮合引擎
来源: PRD 0.2 Section 5.1 & Function/F3

v3.2: 与 Job Queue 解耦，通过依赖注入使用 JobQueueService
v3.3: 添加内存泄漏防护机制
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from threading import Lock
import logging

from .queue import JobQueueService, QueueStats, create_queue
from ..models import Job, Node, Match, JobStatus, NodeStatus
from config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 默认内存记录 TTL（秒）
DEFAULT_MATCH_TTL_SECONDS = 3600  # 1 小时
DEFAULT_JOB_TTL_SECONDS = 300  # 5 分钟
DEFAULT_CLEANUP_INTERVAL_SECONDS = 60  # 1 分钟清理一次


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class RecordMetadata:
    """记录元数据（用于 TTL 管理）。"""
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime = field(default_factory=datetime.utcnow)
    
    def touch(self) -> None:
        """更新最后访问时间。"""
        self.last_accessed = datetime.utcnow()
    
    def is_expired(self, ttl: timedelta) -> bool:
        """检查是否过期。"""
        return datetime.utcnow() - self.created_at > ttl


# ============================================================================
# MatchingService
# ============================================================================

class MatchingService:
    """撮合引擎服务。

    职责:
        - 消费 Job Queue 中的 Job
        - 匹配 Node（从 NodeStatusStore 读取节点状态）
        - 创建 Match 记录
        - 自动清理过期记录（防止内存泄漏）

    注意:
        - Node 状态从 NodeStatusStore 读取，不维护本地列表
        - 只维护 Match 记录
    """
    
    def __init__(
        self,
        queue: Optional[JobQueueService] = None,
        match_ttl_seconds: int = DEFAULT_MATCH_TTL_SECONDS,
        job_ttl_seconds: int = DEFAULT_JOB_TTL_SECONDS,
        cleanup_interval_seconds: int = DEFAULT_CLEANUP_INTERVAL_SECONDS,
    ) -> None:
        """初始化撮合服务。

        Args:
            queue: Job 队列服务（注入依赖）。
            match_ttl_seconds: Match 记录 TTL（秒），默认 1 小时。
            job_ttl_seconds: Job 记录 TTL（秒），默认 5 分钟。
            cleanup_interval_seconds: 清理间隔（秒），默认 1 分钟。
        """
        # 依赖注入
        self._queue: Optional[JobQueueService] = queue
        self._lock: Lock = Lock()  # 线程锁
        
        # TTL 配置
        self._match_ttl: timedelta = timedelta(seconds=match_ttl_seconds)
        self._job_ttl: timedelta = timedelta(seconds=job_ttl_seconds)
        self._cleanup_interval: timedelta = timedelta(seconds=cleanup_interval_seconds)
        self._last_cleanup: datetime = datetime.utcnow()
        
        # 统计数据
        self._cleanup_count: int = 0
        self._records_cleaned: int = 0
        
        # 只维护 Match 记录，不维护 Node 列表
        self._matches: Dict[str, Match] = {}  # match_id -> Match
        self._match_metadata: Dict[str, RecordMetadata] = {}  # match_id -> metadata
        self._job_to_match: Dict[str, str] = {}  # job_id -> match_id
        self._job_metadata: Dict[str, RecordMetadata] = {}  # job_id -> metadata
        self._node_jobs: Dict[str, str] = {}  # node_id -> match_id
        self._pending_jobs: Dict[str, Job] = {}  # 本地待撮合队列
    
    @property
    def queue(self) -> JobQueueService:
        """获取 Job Queue（懒加载，自动根据配置选择）。"""
        if self._queue is None:
            self._queue = create_queue()  # 读取配置: in_memory=true → InMemory, false → Redis
        return self._queue
    
    def _maybe_cleanup(self) -> None:
        """检查是否需要清理（基于时间间隔）。"""
        now = datetime.utcnow()
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup()
            self._last_cleanup = now
    
    def _cleanup(self) -> int:
        """清理过期的记录。

        Returns:
            清理的记录数量。
        """
        cleaned = 0
        now = datetime.utcnow()
        
        # 清理过期的 Match
        expired_matches = [
            match_id for match_id, meta in self._match_metadata.items()
            if now - meta.created_at > self._match_ttl
        ]
        for match_id in expired_matches:
            self._matches.pop(match_id, None)
            self._match_metadata.pop(match_id, None)
            cleaned += 1
        
        # 清理过期的 Job 映射
        expired_jobs = [
            job_id for job_id, meta in self._job_metadata.items()
            if now - meta.created_at > self._job_ttl
        ]
        for job_id in expired_jobs:
            self._job_to_match.pop(job_id, None)
            self._job_metadata.pop(job_id, None)
            self._pending_jobs.pop(job_id, None)
            cleaned += 1
        
        if cleaned > 0:
            self._cleanup_count += 1
            self._records_cleaned += cleaned
            logger.info(
                f"[Cleanup] Cleaned {cleaned} expired records. "
                f"Total: {self._records_cleaned} records in {self._cleanup_count} runs."
            )
        
        return cleaned
    
    def cleanup(self) -> Dict[str, int]:
        """手动触发清理。

        Returns:
            清理统计信息。
        """
        with self._lock:
            cleaned = self._cleanup()
            return {
                "cleaned": cleaned,
                "total_cleaned": self._records_cleaned,
                "cleanup_runs": self._cleanup_count,
                "remaining_matches": len(self._matches),
                "remaining_pending_jobs": len(self._pending_jobs),
            }
    
    def add_job(self, job: Job) -> str:
        """添加 Job 到队列（通过 Job Queue）。

        Args:
            job: Job 对象。

        Returns:
            job_id。
        """
        # 入队到 Job Queue
        job_data = job.model_dump()
        # 添加兼容字段 model (InMemoryQueue 检查 model 或 model_requirement)
        job_data["model"] = job.model
        
        with self._lock:
            # 先检查是否需要清理
            self._maybe_cleanup()
            
            # 保存到本地（向后兼容）
            self._pending_jobs[job.job_id] = job
            
            # 记录元数据（用于 TTL 清理）
            self._job_metadata[job.job_id] = RecordMetadata()
        
        return self.queue.enqueue(job_data)
    
    def remove_job(self, job_id: str) -> None:
        """从队列移除 Job。

        Args:
            job_id: Job ID。
        """
        with self._lock:
            self._pending_jobs.pop(job_id, None)  # 从本地队列移除
            self._job_metadata.pop(job_id, None)  # 清理元数据
            # 注意: 不清理 _job_to_match，因为可能还有其他地方引用
    
    def remove_match(self, match_id: str) -> None:
        """从内存移除 Match 记录。

        Args:
            match_id: Match ID。
        """
        with self._lock:
            match = self._matches.pop(match_id, None)
            self._match_metadata.pop(match_id, None)
            
            if match:
                # 清理反向索引
                self._job_to_match.pop(match.job_id, None)
                self._node_jobs.pop(match.node_id, None)
            
            logger.debug(f"Removed match {match_id} from memory")
    
    def trigger_match(self, job_id: str) -> Optional[Match]:
        """触发撮合（Job 提交时调用）。

        优先从本地 _pending_jobs 查找（向后兼容）。
        如果找不到，尝试从 Job Queue 获取。

        Args:
            job_id: Job ID。

        Returns:
            Match 对象，如果撮合成功；否则返回 None。
        """
        with self._lock:
            # 先从本地队列查找
            job = self._pending_jobs.get(job_id)
        
        if job:
            logger.debug(f"trigger_match: found job {job_id}, calling _match()")
            match = self._match(job)
            logger.debug(f"trigger_match: _match returned {match}")
            if match:
                # 从本地队列移除
                self.remove_job(job_id)
                # 从 Job Queue 中移除（标记为已处理）
                self.queue.acknowledge(job_id)
                return match
        else:
            logger.debug(f"trigger_match: job {job_id} not found in _pending_jobs")
        return None
    
    def consume_queue(self, timeout: float = 1.0) -> Optional[Match]:
        """从 Job Queue 消费 Job 并撮合。

        Args:
            timeout: 出队等待时间（秒）。

        Returns:
            Match 对象，如果撮合成功；否则返回 None。
        """
        # 出队
        job_data = self.queue.dequeue(timeout=timeout)
        
        if not job_data:
            return None
        
        # 转换为 Job 对象 (简化版本)
        job = Job(**job_data)
        
        # 执行撮合
        match = self._match(job)
        
        if match:
            # 确认消费
            self.queue.acknowledge(job.job_id)
        else:
            # 重新入队
            self.queue.retry(job.job_id, delay=5.0)
        
        return match
    
    def poll_node(self, node_id: str) -> Optional[Match]:
        """节点拉取时触发撮合。

        只依赖 NodeStatusStore，不查询 DB。

        Args:
            node_id: Node ID。

        Returns:
            Match 对象，如果撮合成功；否则返回 None。
        """
        # ═══════════════════════════════════════════════════════════════
        # 第一步: 检查节点是否已被匹配
        # ═══════════════════════════════════════════════════════════════
        
        with self._lock:
            if node_id in self._node_jobs:
                match_id = self._node_jobs[node_id]
                logger.info(f"[POLL] Node {node_id[:16]} already matched: {match_id}")
                # 更新访问时间
                if match_id in self._match_metadata:
                    self._match_metadata[match_id].touch()
                return self._matches.get(match_id)
        
        # ═══════════════════════════════════════════════════════════════
        # 第二步: 从 NodeStatusStore 检查节点是否在线
        # ═══════════════════════════════════════════════════════════════
        
        from .node_status_store import get_node_info, node_status_store
        node_info = get_node_info(node_id)
        
        if not node_info:
            logger.info(f"[POLL] Node {node_id[:16]} not in NodeStatusStore")
            return None
        
        if not node_info.is_online:
            logger.info(f"[POLL] Node {node_id[:16]} is offline")
            return None
        
        logger.info(f"[POLL] Node {node_id[:16]} is online: model_support={node_info.model_support}, ask={node_info.ask_price}")
        
        # ═══════════════════════════════════════════════════════════════
        # 第三步: 获取节点实时状态
        # ═══════════════════════════════════════════════════════════════
        
        node_status = node_status_store.get_node_status(node_id)
        
        # ═══════════════════════════════════════════════════════════════
        # 第四步: 从 NodeStatusStore 构建 Node 对象
        # ═══════════════════════════════════════════════════════════════
        
        # 从 raw_data 获取 user_id
        user_id = ""
        if node_info.raw_data:
            user_id = node_info.raw_data.get("user_id", "")
        
        # 提取 region from cluster_id (格式: C_usw_P_Q_A_3f2e)
        region = "unknown"
        if node_info.cluster_id:
            parts = node_info.cluster_id.split("_")
            if len(parts) >= 2:
                region = parts[1][:3] if len(parts[1]) >= 3 else parts[1]
        
        # 构建 Node 对象 (只从 NodeStatusStore 获取数据)
        node = Node(
            node_id=node_info.node_id,
            user_id=user_id,
            runtime={
                'type': 'ollama',
                'loaded_models': node_info.model_support or []
            },
            hardware={
                'gpu_type': node_info.raw_data.get('gpu_type', 'unknown') if node_info.raw_data else 'unknown',
                'gpu_count': node_info.gpu_count or 1
            },
            reliability={
                'avg_latency_ms': node_info.avg_latency or 100,
                'success_rate': 0.95,
                'quality_score': 0.9
            },
            pricing={
                'ask_price_usdc_per_mtoken': node_info.ask_price or 0.001
            },
            location={'region': region},
        )
        
        # 设置实时容量
        node.state.available_concurrency = node_status.get('available_concurrency', 1)
        node.state.available_queue_tokens = node_status.get('available_queue_tokens', 1500)
        
        # ═══════════════════════════════════════════════════════════════
        # 第五步: 从 Queue 获取待匹配 Jobs
        # ═══════════════════════════════════════════════════════════════
        
        pending_jobs_data = self.queue.get_pending_jobs()
        
        if not pending_jobs_data:
            logger.info(f"[POLL] No pending jobs")
            return None
        
        # 分离: 指定模型任务 和 通用任务
        generic_jobs = []
        model_jobs = []
        
        with self._lock:
            for job_data in pending_jobs_data:
                job = Job(**job_data)
                
                # 跳过已匹配的 Job
                if job.job_id in self._job_to_match:
                    continue
                
                if not job.model:
                    generic_jobs.append(job)
                else:
                    model_jobs.append(job)
        
        logger.info(f"[POLL] Pending jobs: {len(model_jobs)} model jobs, {len(generic_jobs)} generic jobs")
        
        # ═══════════════════════════════════════════════════════════════
        # 第六步: 匹配
        # ═══════════════════════════════════════════════════════════════
        
        # 先处理指定模型的 Jobs
        for job in model_jobs:
            if self._can_match(job, node, node_status):
                logger.info(f"[POLL] Matched model job: {job.job_id}")
                match = self._create_match(job, node)
                if match:
                    self.queue.acknowledge(job.job_id)
                    return match
        
        # 再处理通用 Jobs (按评分排序)
        if generic_jobs:
            sorted_generic = sorted(
                generic_jobs,
                key=lambda j: (-self._get_match_score(j, node), j.created_at)
            )
            
            for job in sorted_generic:
                if self._can_match(job, node, node_status):
                    logger.info(f"[POLL] Matched generic job: {job.job_id}")
                    match = self._create_match(job, node)
                    if match:
                        self.queue.acknowledge(job.job_id)
                        return match
        
        logger.info(f"[POLL] No job matched for node {node_id[:16]}")
        return None
    
    def get_match(self, match_id: str) -> Optional[Match]:
        """根据 Match ID 获取 Match。

        Args:
            match_id: Match ID。

        Returns:
            Match 或 None。
        """
        with self._lock:
            # 更新最后访问时间
            if match_id in self._match_metadata:
                self._match_metadata[match_id].touch()
            return self._matches.get(match_id)
    
    def get_match_by_job(self, job_id: str) -> Optional[Match]:
        """根据 Job ID 获取 Match。

        Args:
            job_id: Job ID。

        Returns:
            Match 或 None。
        """
        with self._lock:
            match_id = self._job_to_match.get(job_id)
            if match_id and match_id in self._match_metadata:
                self._match_metadata[match_id].touch()  # 更新访问时间
            return self._matches.get(match_id) if match_id else None
    
    def get_node_prelock_jobs(self, node_id: str) -> List[Job]:
        """获取节点的 Pre-lock Jobs。

        Args:
            node_id: Node ID。

        Returns:
            Pre-lock Job 列表。
        """
        with self._lock:
            prelock_jobs: List[Job] = []
            pending = self.queue.get_pending_jobs()
            pending_ids = {j.get("job_id") for j in pending}
            
            for match_id, match in self._matches.items():
                if match.node_id == node_id and match.job_id in pending_ids:
                    # 查找 Job 数据
                    for job_data in pending:
                        if job_data.get("job_id") == match.job_id:
                            job = Job(**job_data)
                            if job.status == JobStatus.PRE_LOCKED:
                                prelock_jobs.append(job)
                            break
            return prelock_jobs
    
    def _get_model_family(self, model_name: str) -> str:
        """从模型名提取 family。

        Args:
            model_name: 模型名称。

        Returns:
            模型家族名称。
        """
        model_lower = model_name.lower()
        for family in ["qwen", "llama", "gemma", "mistral", "phi", "codellama"]:
            if family in model_lower:
                return family
        return model_name.split(":")[0] if ":" in model_name else model_name
    
    def _match(self, job: Job) -> Optional[Match]:
        """执行撮合逻辑（两阶段分层匹配）。

        第一阶段: 获取所有在线节点。
        第二阶段: 过滤与排序（模型、容量、价格、延迟）。
        第三阶段: 构建 Node 对象并创建 Match。

        Args:
            job: Job 对象。

        Returns:
            Match 对象，如果撮合成功；否则返回 None。
        """
        logger.debug(f"_match() called for job {job.job_id}, model={job.model}")
        
        from .node_status_store import list_online_nodes
        
        # ═══════════════════════════════════════════════════════════════
        # 第一阶段: 获取在线节点
        # ═══════════════════════════════════════════════════════════════
        
        online_nodes = list_online_nodes(max_age_seconds=10)
        logger.debug(f"Online nodes count: {len(online_nodes)}")
        
        if not online_nodes:
            logger.info("No online nodes available")
            return None
        
        # ═══════════════════════════════════════════════════════════════
        # 第二阶段: 过滤与排序
        # ═══════════════════════════════════════════════════════════════
        
        # 计算 Job 需要的 tokens
        job_tokens = job.input_tokens + job.output_tokens_limit
        
        # 价格比较: job.bid_price vs node.ask_price (均为 USDC per token)
        # job 出价必须 >= node 要价
        
        candidates = []
        
        for node_info in online_nodes:
            # 1. 容量检查
            if node_info.available_queue_tokens < job_tokens:
                logger.debug(f"Node {node_info.node_id[:16]} capacity fail: {node_info.available_queue_tokens} < {job_tokens}")
                continue
            
            # 2. 模型匹配
            if job.model:
                model_match = False
                for supported in node_info.model_support:
                    # 支持精确匹配、前缀匹配
                    if (supported == job.model or
                        job.model.startswith(supported) or
                        supported.startswith(job.model)):
                        model_match = True
                        break
                
                if not model_match:
                    logger.debug(f"Node {node_info.node_id[:16]} model mismatch")
                    continue
            
            # 3. 价格检查 (per-token 直接比较)
            if job.bid_price < node_info.ask_price:
                logger.debug(f"Node {node_info.node_id[:16]} price fail: bid={job.bid_price} < ask={node_info.ask_price}")
                continue
            
            # 4. 延迟检查
            if node_info.avg_latency > job.max_latency:
                logger.debug(f"Node {node_info.node_id[:16]} latency fail: {node_info.avg_latency} > {job.max_latency}")
                continue
            
            # 通过所有检查，加入候选
            candidates.append(node_info)
        
        logger.debug(f"Candidates count: {len(candidates)}")
        
        if not candidates:
            return None
        
        # ═══════════════════════════════════════════════════════════════
        # 第三阶段: 选择最优并创建 Match
        # ═══════════════════════════════════════════════════════════════
        
        # 按价格排序 (最低价优先，相同时按延迟)
        candidates.sort(key=lambda n: (n.ask_price, n.avg_latency))
        
        best_node = candidates[0]
        logger.debug(f"Selected node: {best_node.node_id[:16]}, ask={best_node.ask_price}")
        
        # 从 raw_data 获取 user_id（如果有）
        user_id = best_node.raw_data.get("user_id", "") if best_node.raw_data else ""
        
        # 提取 region from cluster_id (格式: C_usw_P_Q_A_3f2e)
        region = "unknown"
        if best_node.cluster_id:
            parts = best_node.cluster_id.split("_")
            if len(parts) >= 2:
                region = parts[1][:3] if len(parts[1]) >= 3 else parts[1]
        
        # 构建 Node 对象
        node = Node(
            node_id=best_node.node_id,
            user_id=user_id,
            runtime={
                'type': 'ollama',
                'loaded_models': best_node.model_support or []
            },
            hardware={
                'gpu_type': 'unknown',
                'gpu_count': best_node.gpu_count or 1
            },
            reliability={
                'avg_latency_ms': best_node.avg_latency,
                'success_rate': 0.95,
                'quality_score': 0.9
            },
            pricing={
                'ask_price_usdc_per_mtoken': best_node.ask_price
            },
            location={'region': region},
        )
        
        # 设置实时容量
        node.state.available_concurrency = best_node.available_concurrency
        node.state.available_queue_tokens = best_node.available_queue_tokens
        
        # 创建 Match
        return self._create_match(job, node)
    
    def _can_match(
        self,
        job: Job,
        node: Node,
        node_status: Optional[Dict[str, Any]] = None
    ) -> bool:
        """检查是否可以撮合（从 NodeStatusStore 获取容量）。

        匹配规则:
            - job.model: 精确匹配 model_support（支持前缀匹配如 qwen → qwen2.5:7b）。
            - job.model 为空: 匹配任何可用节点（由系统分配排名第一的）。

        Args:
            job: Job 对象。
            node: Node 对象。
            node_status: 节点实时状态（可选）。

        Returns:
            True 如果可以撮合，否则返回 False。
        """
        logger.debug(f"_can_match: job model={job.model}, bid={job.bid_price}, max_lat={job.max_latency}")
        
        # 模型匹配
        if job.model:
            # 检查是否为完整模型名
            if job.model in node.model_support:
                logger.debug(f"Model exact match: {job.model}")
            else:
                # 尝试前缀匹配（如 qwen 匹配 qwen2.5:7b）
                family_found = False
                for m in node.model_support:
                    if m.startswith(job.model):
                        family_found = True
                        break
                if not family_found:
                    logger.debug(f"Model NO match")
                    return False
        # job.model 为空: 不检查模型（匹配任何可用节点）
        
        # 价格匹配 (per-token 直接比较)
        # job 出价 >= node 要价
        if job.bid_price < node.ask_price:
            logger.debug(f"Price fail: bid={job.bid_price} < ask={node.ask_price}")
            return False
        
        # 延迟匹配
        if node.avg_latency > job.max_latency:
            logger.debug(f"Latency fail: {node.avg_latency} > {job.max_latency}")
            return False
        
        # 容量检查（从 node_status 获取）
        if node_status:
            available_tokens = node_status.get('available_queue_tokens', 0)
            job_tokens = job.input_tokens + job.output_tokens_limit
            if available_tokens < job_tokens:
                logger.debug(f"Capacity fail: {available_tokens} < {job_tokens}")
                return False
        
        logger.debug("All checks passed!")
        return True
    
    def _get_job_tokens(self, job: Job) -> int:
        """计算 Job 需要的 token 数。

        Args:
            job: Job 对象。

        Returns:
            Job 需要的总 token 数（input + output）。
        """
        return job.input_tokens + job.output_tokens_limit

    def _get_match_score(self, job: Job, node: Node) -> float:
        """计算匹配得分（用于通用任务选择最优节点）。

        分数越低越优先：
            - 价格权重 50%
            - 延迟权重 30%
            - 成功率权重 20%

        Args:
            job: Job 对象。
            node: Node 对象。

        Returns:
            匹配得分（越低越优先）。
        """
        # 归一化价格 (0-1)
        # 价格分数 = job出价 / node要价 (per-token 直接比较)
        price_score = job.bid_price / max(node.ask_price, 0.000001)
        
        # 归一化延迟 (0-1)
        latency_score = job.max_latency / max(node.avg_latency, 1)
        
        # 成功率分数 (0-1)
        success_score = node.avg_success_rate
        
        # 综合得分 (越低越优)
        return price_score * 0.5 + latency_score * 0.3 + success_score * 0.2
    
    def _create_match(self, job: Job, node: Node) -> Match:
        """创建 Match。

        会在创建 Match 时预留队列容量。

        Args:
            job: Job 对象。
            node: Node 对象。

        Returns:
            创建的 Match 对象。
        """
        # 锁定价格（快照）- 使用节点的要价 (node.ask_price)
        # 如果 job 出价更高，按 node.ask_price 结算，差额退还给 buyer
        locked_price = node.ask_price
        
        # 确定实际使用的模型
        # - 如果 job 指定了 model → 使用该 model
        # - 如果 job 未指定 model → 使用节点支持的第一个模型（最便宜/最快）
        job_model = getattr(job, 'model_requirement', None) or getattr(job, 'model', None)
        if job_model is None and hasattr(node, 'model_support') and node.model_support:
            job_model = node.model_support[0] if node.model_support else "qwen2.5:7b"
        used_model = job_model or "qwen2.5:7b"
        
        # 创建 Match
        match = Match(
            job_id=job.job_id,
            node_id=node.node_id,
            locked_price=locked_price,
            model=used_model,
        )
        
        # 更新状态
        job.status = JobStatus.MATCHED
        job.matched_at = datetime.utcnow()
        node.status = NodeStatus.BUSY
        
        # 存储到内存
        with self._lock:
            self._matches[match.match_id] = match
            self._match_metadata[match.match_id] = RecordMetadata()
            self._job_to_match[job.job_id] = match.match_id
            self._job_metadata[job.job_id] = RecordMetadata()  # 更新元数据
            self._node_jobs[node.node_id] = match.match_id
        
        logger.info(f"Match created: {match.match_id}, job={job.job_id}, node={node.node_id}")
        
        return match
    
    def release_node(self, node_id: str, tokens: int = 0) -> None:
        """释放节点（Job 完成后）。

        Args:
            node_id: Node ID。
            tokens: 释放的 tokens 数量。
        """
        with self._lock:
            if node_id in self._node_jobs:
                del self._node_jobs[node_id]
                logger.info(f"Node released: {node_id}")
    
    def get_pending_jobs_count(self) -> int:
        """获取待撮合 Job 数量。

        Returns:
            待撮合 Job 数量。
        """
        return len(self.queue.get_pending_jobs())
    
    def get_queue_stats(self) -> QueueStats:
        """获取队列统计。

        Returns:
            队列统计信息。
        """
        return self.queue.get_stats()
    
    def get_pending_jobs(self) -> List[Job]:
        """获取所有待撮合 Jobs。

        Returns:
            Job 列表。
        """
        return list(self._pending_jobs.values())
    
    def get_matches(self) -> List[Match]:
        """获取所有 Match 记录。

        Returns:
            Match 列表。
        """
        return list(self._matches.values())
    
    def get_match_count(self) -> int:
        """获取 Match 总数。

        Returns:
            Match 总数。
        """
        return len(self._matches)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取内存使用统计。

        Returns:
            内存统计信息。
        """
        with self._lock:
            return {
                "matches": len(self._matches),
                "pending_jobs": len(self._pending_jobs),
                "job_to_match": len(self._job_to_match),
                "node_jobs": len(self._node_jobs),
                "match_metadata": len(self._match_metadata),
                "job_metadata": len(self._job_metadata),
                "cleanup_runs": self._cleanup_count,
                "total_cleaned": self._records_cleaned,
                "match_ttl_seconds": int(self._match_ttl.total_seconds()),
                "job_ttl_seconds": int(self._job_ttl.total_seconds()),
                "last_cleanup": self._last_cleanup.isoformat(),
            }


# ============================================================================
# 单例 (使用全局 Job Queue)
# ============================================================================

matching_service = MatchingService()
