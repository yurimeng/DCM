"""
Match Engine 2.0 - DCM v3.2
基于 Node Live Status 的实时匹配

Match 流程 (DCM v3.2):
1. Job 提交
2. 按 Cluster 分类找到候选
3. Hard Filter + Node Live Status 做实时过滤
4. Scoring 评分排序
5. Pre-Lock / Reserve 预留
6. Dispatch: 分发到 Node
7. 执行完成: Release
"""

from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from ..models import (
    Cluster, ClusterStatus, ModelInfo, CapacityInfo, PricingInfo, PerformanceInfo,
    Job, JobStatus, Match, Node
)
from .order_book import OrderBook
from .hard_filter import HardFilter, create_default_filter
from .node_status_store import node_status_store, update_node_status
from .compatibility import CompatibilityMatrix, compatibility_matrix
from .scoring import ScoringFunction, scoring_function
from .pre_lock import PreLockService, PreLockResult, PreLockStatus, pre_lock_service

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果 (DCM v3.1)"""
    success: bool
    pre_locked: bool = False           # 是否已 Pre-Lock
    cluster: Optional[Cluster] = None        # 匹配的 Slot
    job: Optional[Job] = None           # Job 对象
    score: Optional[float] = None      # 匹配评分
    pre_lock_expires_at: Optional[int] = None  # Pre-Lock 过期时间
    reason: Optional[str] = None        # 失败原因


@dataclass
class DispatchResult:
    """分发结果 (DCM v3.1)"""
    success: bool
    job_id: str
    cluster_id: Optional[str] = None
    worker_id: Optional[str] = None
    reason: Optional[str] = None


class MatchEngineV2:
    """
    Match Engine 2.0 - DCM v3.1 Slot-based 撮合引擎
    
    核心功能:
    1. Job/Slot 管理
    2. 匹配算法 (Hard Filter + Scoring)
    3. Pre-Lock 机制
    4. Multi-Job 并发支持
    """
    
    def __init__(
        self,
        order_book: Optional[OrderBook] = None,
        hard_filter: Optional[HardFilter] = None,
        compatibility: Optional[CompatibilityMatrix] = None,
        scoring: Optional[ScoringFunction] = None,
        pre_lock_service: Optional[PreLockService] = None,
    ):
        self.order_book = order_book or OrderBook()
        self.hard_filter = hard_filter or create_default_filter()
        self.compatibility = compatibility or compatibility_matrix
        self.scoring = scoring or scoring_function
        
        # Pre-Lock 服务（使用传入的或创建新的）
        self.pre_lock = pre_lock_service if pre_lock_service else PreLockService()
        
        # 内部状态
        self._slots: Dict[str, Cluster] = {}
        self._matches: Dict[str, Match] = {}
        self._job_to_match: Dict[str, str] = {}  # job_id → match_id
        self._cluster_jobs: Dict[str, str] = {}      # cluster_id → job_id
        self._job_cluster: Dict[str, str] = {}       # job_id → cluster_id
        self._nodes: Dict[str, Node] = {}         # node_id → Node
        
        # Pre-Lock 回调设置
        self.pre_lock.set_callbacks(
            on_confirmed=self._on_pre_lock_confirmed,
            on_expired=self._on_pre_lock_expired,
            on_rejected=self._on_pre_lock_rejected,
        )
    
    # ===== Node 管理 (DCM v3.2) =====
    
    def register_node(self, node: Node) -> None:
        """注册 Node
        
        Args:
            node: Node 对象
        """
        self._nodes[node.node_id] = node
        logger.info(f"Node registered: {node.node_id} (gpu_count={node.gpu_count})")
    
    def unregister_node(self, node_id: str) -> Optional[Node]:
        """注销 Node
        
        Args:
            node_id: Node ID
            
        Returns:
            被注销的 Node
        """
        node = self._nodes.pop(node_id, None)
        if node:
            logger.info(f"Node unregistered: {node_id}")
        return node
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """获取 Node
        
        Args:
            node_id: Node ID
            
        Returns:
            Node 或 None
        """
        return self._nodes.get(node_id)
    
    def update_node_live_status(self, node_id: str, status: Dict) -> None:
        """更新 Node 实时状态
        
        从 Node Agent 接收 Node Live Status Report 时调用
        
        Args:
            node_id: Node ID
            status: Node Live Status Report 数据
        """
        update_node_status(node_id, status)
    
    def update_node_capacity_report(self, node_id: str, report: Dict) -> Optional[str]:
        """更新 Node Capacity Report
        
        从 Node Agent 接收 Node Capacity Report 时调用
        检查并更新 Cluster ID
        
        Args:
            node_id: Node ID
            report: Node Capacity Report 数据
            
        Returns:
            新的 cluster_id 或 None
        """
        from .cluster_builder import build_cluster_id
        
        node = self._nodes.get(node_id)
        if not node:
            return None
        
        # 更新 Node 的 runtime 和 capability
        if "runtime" in report:
            rt = report["runtime"]
            node.runtime.type = rt.get("type", "")
            node.runtime.loaded_models = rt.get("loaded_models", [])
        
        if "capacity" in report:
            cap = report["capacity"]
            node.capability.max_concurrency_total = cap.get("max_concurrency_total", 1)
        
        # 重新计算并更新 Cluster ID
        old_cluster_id = node.network.cluster_id
        new_cluster_id = build_cluster_id(
            region=node.location.region,
            stake_tier=node.economy.stake_tier,
            models=node.runtime.loaded_models,
            quality_score=node.reliability.quality_score,
            success_rate=node.reliability.success_rate,
        )
        
        if old_cluster_id != new_cluster_id:
            node.network.cluster_id = new_cluster_id
            logger.info(f"Node {node_id} cluster changed: {old_cluster_id} -> {new_cluster_id}")
            return new_cluster_id
        
        return None
    
    def _sync_cluster_to_node_queue(self, cluster: Cluster, tokens: int, release: bool = False) -> None:
        """同步 Slot 队列到 Node (DCM v3.2)
        
        当 Slot 队列变化时，同步更新 NodeStatusStore
        
        Args:
            cluster: Slot 对象
            tokens: token 数量
            release: True 表示释放，False 表示预留
        """
        # 使用 NodeStatusStore 而不是直接访问 Node
        current_status = node_status_store.get_node_status(cluster.node_id)
        
        if release:
            # 释放：增加可用 token
            new_available = current_status["available_queue_tokens"] + tokens
        else:
            # 预留：减少可用 token
            new_available = current_status["available_queue_tokens"] - tokens
        
        # 更新 NodeStatusStore
        node_status_store.update(cluster.node_id, {
            "load": {
                "active_jobs": current_status["active_jobs"],
                "available_token_capacity": max(0, new_available)
            }
        })
    
    def _sync_node_to_cluster_queue(self, node: Node, cluster: Cluster) -> None:
        """同步 Node 队列到 Slot (DCM v3.2)
        
        当 Slot 注册时，从 Node 继承队列配置
        
        Args:
            node: Node 对象
            cluster: Slot 对象
        """
        # Slot 的 max_queue = Node 的 runtime.queue_capacity 或默认值
        max_queue = getattr(node.runtime, 'queue_capacity', 1500) if hasattr(node, 'runtime') else 1500
        cluster.capacity.max_queue = max_queue
        cluster.capacity.available_queue = max_queue
    
    # ===== Cluster 管理 =====
    
    def register_cluster(self, cluster: Cluster) -> None:
        """注册 Cluster (DCM v3.2: 同步 Node 队列)"""
        self._slots[cluster.cluster_id] = cluster
        
        # 从 Node 同步队列配置
        node = self._nodes.get(cluster.node_id)
        if node:
            self._sync_node_to_cluster_queue(node, cluster)
        
        self.order_book.add_cluster(cluster)
        logger.info(f"Cluster registered: {cluster.cluster_id} ({cluster.model.name})")
    
    # 别名兼容
    def register_slot(self, cluster: Cluster) -> None:
        """注册 Slot (兼容别名)"""
        return self.register_cluster(cluster)
    
    def unregister_cluster(self, cluster_id: str) -> Optional[Cluster]:
        """注销 Cluster"""
        cluster = self._slots.pop(cluster_id, None)
        if cluster:
            self.order_book.remove_cluster(cluster_id)
            logger.info(f"Cluster unregistered: {cluster_id}")
        return cluster
    
    # 别名兼容
    def unregister_slot(self, cluster_id: str) -> Optional[Cluster]:
        """注销 Slot (兼容别名)"""
        return self.unregister_cluster(cluster_id)
    
    def get_cluster(self, cluster_id: str) -> Optional[Cluster]:
        """获取 Cluster"""
        return self._slots.get(cluster_id)
    
    # 别名兼容
    def get_slot(self, cluster_id: str) -> Optional[Cluster]:
        """获取 Slot (兼容别名)"""
        return self.get_cluster(cluster_id)
    
    # ===== Job 管理 =====
    
    def submit_job(self, job: Job) -> None:
        """提交 Job"""
        self.order_book.add_job(job)
        logger.info(f"Job submitted: {job.job_id} (model: {job.model_requirement})")
    
    def cancel_job(self, job_id: str) -> Optional[Job]:
        """取消 Job（支持已匹配的 Job）"""
        job = self.order_book.remove_job(job_id)
        
        # 如果不在 order book，尝试从 _job_cluster 查找
        if not job:
            cluster_id = self._job_cluster.get(job_id)
            if cluster_id:
                cluster = self.get_cluster(cluster_id)
                if cluster:
                    # 释放锁
                    cluster.release_lock(job_id)
                self._job_cluster.pop(job_id, None)
                logger.info(f"Job cancelled (matched): {job_id}")
                # 返回一个标记对象
                class CancelledJob:
                    job_id: str
                    status: str = "cancelled"
                return CancelledJob()
        else:
            # 释放相关锁
            cluster_id = self._job_cluster.get(job_id)
            if cluster_id:
                cluster = self.get_cluster(cluster_id)
                if cluster:
                    cluster.release_lock(job_id)
                self._job_cluster.pop(job_id, None)
            logger.info(f"Job cancelled: {job_id}")
        
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """获取 Job"""
        for job in self.order_book.get_all_jobs():
            if job.job_id == job_id:
                return job
        return None
    
    # ===== 匹配核心 (DCM v3.2 基于 Node Live Status) =====
    
    def _get_candidate_nodes(self, job: Job) -> List[Node]:
        """
        获取候选 Nodes
        
        1. 按 Cluster 分类找到候选
        2. 从 Cluster 获取关联的 Node
        
        Args:
            job: Job 对象
            
        Returns:
            候选 Nodes 列表
        """
        # 从 OrderBook 获取候选 Clusters
        family = None
        if job.model_requirement:
            import re
            base = job.model_requirement.split(":")[0]
            match = re.match(r'^([a-zA-Z]+)', base)
            family = match.group(1).lower() if match else base.lower()
        
        clusters = self.order_book.get_slots(family)
        if not clusters:
            clusters = self.order_book.get_slots()
        
        if not clusters:
            return []
        
        # 从 Cluster 获取关联的 Nodes
        nodes = []
        for cluster in clusters:
            # Cluster 的 node_ids 列表
            for node_id in cluster.node_ids:
                node = self._nodes.get(node_id)
                if node:
                    nodes.append(node)
        
        return nodes
    
    def _filter_and_rank_nodes(self, nodes: List[Node], job: Job) -> List[Tuple[Node, float]]:
        """
        过滤并排序 Nodes
        
        1. Hard Filter 使用 Node Live Status
        2. Scoring 评分
        
        Args:
            nodes: 候选 Nodes
            job: Job 对象
            
        Returns:
            (Node, score) 列表，按 score 降序
        """
        from .hard_filter import node_status_store
        
        # Hard Filter
        filtered = self.hard_filter.get_passing_nodes(nodes, job)
        
        if not filtered:
            return []
        
        # Scoring
        return self.scoring.rank_nodes(filtered, job)
    
    def _get_candidate_clusters(self, job: Job) -> List[Cluster]:
        """
        获取候选 Clusters (向后兼容 Slot 测试)
        
        Args:
            job: Job 对象
            
        Returns:
            候选 Clusters 列表
        """
        import re
        
        # 从 OrderBook 获取候选 Clusters
        family = None
        if job.model_requirement:
            base = job.model_requirement.split(":")[0]
            match = re.match(r'^([a-zA-Z]+)', base)
            family = match.group(1).lower() if match else base.lower()
        
        clusters = self.order_book.get_slots(family)
        if not clusters:
            clusters = self.order_book.get_slots()
        
        # 过滤可用的 Clusters
        available = [c for c in clusters if c.is_available()]
        
        return available
    
    def _filter_and_rank_clusters(self, clusters: List[Cluster], job: Job) -> List[Tuple[Cluster, float]]:
        """
        过滤并排序 Clusters (向后兼容)
        
        1. 简化 Hard Filter (主要检查价格、延迟和模型版本)
        2. Scoring 评分
        
        Args:
            clusters: 候选 Clusters
            job: Job 对象
            
        Returns:
            (Cluster, score) 列表，按 score 降序
        """
        # 简化过滤：检查价格、延迟和模型版本
        filtered = []
        for cluster in clusters:
            # 价格检查
            if cluster.pricing.output_price > job.bid_price:
                continue
            
            # 延迟检查
            if cluster.performance.avg_latency_ms > job.max_latency:
                continue
            
            # 模型版本检查 (DCM v3.1 兼容性)
            if job.model_requirement:
                job_req = job.model_requirement.lower()
                cluster_model = cluster.model.name.lower()
                
                # 完全匹配
                if job_req == cluster_model:
                    pass
                # 版本向下兼容 (e.g., qwen3.5:latest can serve qwen3-8b)
                elif job_req in cluster_model:
                    pass
                # 家族匹配，但版本要求更严格 (e.g., qwen3.5:latest cannot serve qwen2.5)
                elif ":latest" in cluster_model and job_req not in cluster_model:
                    # 检查基础家族
                    job_family = job_req.split(":")[0].split("-")[0]
                    cluster_family = cluster_model.split(":")[0].split("-")[0]
                    if job_family == cluster_family:
                        # 家族相同但版本不同，需要检查
                        # 这里简化处理：如果 job_req 是更高的版本要求，拒绝
                        continue
                # 家族不匹配
                elif not any(f in cluster_model for f in [job_req, job_req.split(":")[0].split("-")[0]]):
                    continue
            
            filtered.append(cluster)
        
        if not filtered:
            return []
        
        # Scoring - 使用 Cluster 的基本信息
        ranked = []
        for cluster in filtered:
            # 简单评分公式
            price_ratio = cluster.pricing.output_price / job.bid_price if job.bid_price > 0 else 1
            latency_ratio = cluster.performance.avg_latency_ms / job.max_latency if job.max_latency > 0 else 1
            
            # 分数越高越好（价格低、延迟低）
            score = 1.0 / (price_ratio * latency_ratio + 0.1)
            
            # 考虑并发容量
            score *= cluster.capacity.available_capacity
            
            ranked.append((cluster, score))
        
        # 按分数降序排序
        ranked.sort(key=lambda x: x[1], reverse=True)
        
        return ranked
    
    def match_job(self, job_id: str, pre_lock_ttl_ms: int = 5000) -> MatchResult:
        """
        为 Job 匹配最优 Node (DCM v3.2)
        
        匹配流程:
        1. 按 Cluster 分类找到候选
        2. Hard Filter + Node Live Status 做实时过滤
        3. Scoring 评分排序
        4. 直接匹配或 Pre-Lock
        
        Args:
            job_id: Job ID
            pre_lock_ttl_ms: Pre-Lock TTL (毫秒)
            
        Returns:
            MatchResult
        """
        job = self.get_job(job_id)
        if not job:
            return MatchResult(success=False, reason="job_not_found")
        
        # 计算 Job 需要的 token 数
        job_tokens = job.input_tokens + job.output_tokens_limit
        
        # 获取候选 Clusters
        candidate_clusters = self._get_candidate_clusters(job)
        if not candidate_clusters:
            return MatchResult(success=False, reason="no_available_slots")  # 兼容测试
        
        # 过滤并排序 Clusters
        ranked = self._filter_and_rank_clusters(candidate_clusters, job)
        if not ranked:
            return MatchResult(success=False, reason="no_clusters_passed_filter")
        
        # 按排序结果尝试匹配
        for best_cluster, best_score in ranked:
            # 直接匹配条件：并发有空间 且 队列足够
            if best_cluster.capacity.available_capacity > 0 and best_cluster.capacity.available_queue >= job_tokens:
                # 直接匹配
                result = self._try_direct_match(job, best_cluster, best_score)
                if result.success:
                    return result
            # PreLock 条件：并发有空间（即使队列不足，等待队列释放）
            elif best_cluster.capacity.available_capacity > 0:
                # 清理该 Cluster 上过期的 Pre-Locks
                self.pre_lock.cleanup_cluster_expired(best_cluster)
                
                # 请求 Pre-Lock (包含 token 预留)
                pre_lock_result = self.pre_lock.request_pre_lock(
                    job_id, best_cluster, pre_lock_ttl_ms, tokens=job_tokens
                )
                
                if pre_lock_result.success:
                    # Pre-Lock 成功，立即 Ack 确认
                    ack_result = self.pre_lock.receive_ack(job_id, best_cluster)
                    
                    if ack_result.success:
                        # 同步到 Node (DCM v3.2)
                        self._sync_cluster_to_node_queue(best_cluster, job_tokens, release=False)
                        
                        # 更新 Job 状态
                        job.status = JobStatus.MATCHED
                        job.matched_at = datetime.utcnow()
                        job.cluster_id = best_cluster.cluster_id
                        job.node_id = best_cluster.node_id
                        job.worker_id = best_cluster.worker_id
                        
                        # 创建 Match
                        match = Match(
                            job_id=job.job_id,
                            cluster_id=best_cluster.cluster_id,
                            node_id=best_cluster.node_id,
                            worker_id=best_cluster.worker_id,
                            locked_price=job.bid_price,
                            model=best_cluster.model.name,
                        )
                        self._matches[match.match_id] = match
                        self._job_to_match[job.job_id] = match.match_id
                        self._job_cluster[job.job_id] = best_cluster.cluster_id
                        
                        # 从 Order Book 移除 Job
                        self.order_book.remove_job(job.job_id)
                        
                        logger.info(f"Match created (pre-lock): {match.match_id} (job={job.job_id}, slot={best_cluster.cluster_id}, score={best_score:.3f})")
                        
                        return MatchResult(
                            success=True,
                            pre_locked=True,
                            cluster=best_cluster,
                            job=job,
                            score=best_score,
                            pre_lock_expires_at=pre_lock_result.expires_at,
                        )
                    else:
                        # Ack 失败，释放锁 (会释放 token)
                        best_cluster.release_lock(job_id)
                
                # 当前 Slot Pre-Lock 失败，尝试下一个
                logger.debug(f"Pre-Lock failed for slot {best_cluster.cluster_id}, trying next")
        
        return MatchResult(success=False, reason="all_slots_match_failed")
    
    def _try_direct_match(self, job: Job, cluster: Cluster, score: float) -> MatchResult:
        """尝试直接匹配 Slot (DCM v3.2)
        
        调用此方法时，已确保 available_queue >= job_tokens
        
        Args:
            job: Job 对象
            cluster: Slot 对象
            score: 匹配评分
            
        Returns:
            MatchResult
        """
        # 计算 Job 需要的 token 数 (input + output)
        job_tokens = job.input_tokens + job.output_tokens_limit
        
        # 预留队列容量
        if not cluster.capacity.reserve_queue(job_tokens):
            return MatchResult(success=False, reason="queue_reserve_failed")
        
        # 使用统一的 reserve 方法预约 Slot
        if not cluster.reserve(job.job_id, tokens=job_tokens):
            return MatchResult(success=False, reason="cluster_reserve_failed")
        
        # 同步到 Node (DCM v3.2)
        self._sync_cluster_to_node_queue(cluster, job_tokens)
        
        # 更新 Job 状态
        job.status = JobStatus.MATCHED
        job.matched_at = datetime.utcnow()
        job.cluster_id = cluster.cluster_id
        job.node_id = cluster.node_id
        job.worker_id = cluster.worker_id
        
        # 创建 Match
        match = Match(
            job_id=job.job_id,
            cluster_id=cluster.cluster_id,
            node_id=cluster.node_id,
            worker_id=cluster.worker_id,
            locked_price=job.bid_price,
            model=cluster.model.name,
        )
        self._matches[match.match_id] = match
        self._job_to_match[job.job_id] = match.match_id
        self._job_cluster[job.job_id] = cluster.cluster_id
        
        # 从 Order Book 移除 Job
        self.order_book.remove_job(job.job_id)
        
        logger.info(f"Match created (direct): {match.match_id} (job={job.job_id}, slot={cluster.cluster_id}, score={score:.3f})")
        
        return MatchResult(
            success=True,
            pre_locked=False,  # 直接匹配，无需 pre-lock
            cluster=cluster,
            job=job,
            score=score,
        )
    
    def match_job_simple(self, job_id: str) -> MatchResult:
        """
        简化的匹配（无 Pre-Lock，用于向后兼容）
        """
        job = self.get_job(job_id)
        if not job:
            return MatchResult(success=False, reason="job_not_found")
        
        family = None
        if job.model_requirement:
            import re
            base = job.model_requirement.split(":")[0]
            match = re.match(r'^([a-zA-Z]+)', base)
            family = match.group(1).lower() if match else base.lower()
        
        candidate_slots = self.order_book.get_slots(family)
        if not candidate_slots:
            if not job.model_requirement:
                candidate_slots = self.order_book.get_slots()
        
        if not candidate_slots:
            return MatchResult(success=False, reason="no_available_slots")
        
        filtered_slots = self.hard_filter.filter_many(candidate_slots, job)
        if not filtered_slots:
            return MatchResult(success=False, reason="no_slots_passed_filter")
        
        ranked = self.scoring.rank_slots(filtered_slots, job)
        best_cluster, best_score = ranked[0]
        
        # 直接预约
        if best_cluster.reserve(job.job_id):
            if not best_cluster.is_available():
                self.order_book.remove_slot(best_cluster.cluster_id)
            
            match = Match(
                job_id=job.job_id,
                cluster_id=best_cluster.cluster_id,
                node_id=best_cluster.node_id,
                worker_id=best_cluster.worker_id,
                locked_price=job.bid_price,
                model=best_cluster.model.name,
            )
            
            self._matches[match.match_id] = match
            self._job_to_match[job.job_id] = match.match_id
            self._cluster_jobs[best_cluster.cluster_id] = job.job_id
            
            self.order_book.remove_job(job.job_id)
            
            job.status = JobStatus.MATCHED
            job.matched_at = datetime.utcnow()
            job.cluster_id = best_cluster.cluster_id
            
            logger.info(f"Match created: {match.match_id} (job={job.job_id}, slot={best_cluster.cluster_id}, score={best_score:.3f})")
            
            return MatchResult(
                success=True,
                cluster=best_cluster,
                job=job,
                score=best_score,
            )
        
        return MatchResult(success=False, reason="reserve_failed")
    
    # ===== Dispatch (DCM v3.1) =====
    
    def dispatch_job(self, job_id: str) -> DispatchResult:
        """
        分发 Job 到 Worker 执行
        
        Args:
            job_id: Job ID
            
        Returns:
            DispatchResult
        """
        # 先检查是否已分配 cluster
        cluster_id = self._job_cluster.get(job_id)
        if not cluster_id:
            return DispatchResult(success=False, job_id=job_id, reason="no_cluster_assigned")
        
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            return DispatchResult(success=False, job_id=job_id, cluster_id=cluster_id, reason="cluster_not_found")
        
        # 检查 Job 是否在 reserved 列表
        if job_id not in cluster.job_sets.reserved:
            return DispatchResult(success=False, job_id=job_id, cluster_id=cluster_id, reason="job_not_reserved")
        
        # 尝试获取 Job（可能在 order book 中）
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.DISPATCHED
            job.dispatched_at = datetime.utcnow()
        
        logger.info(f"Job dispatched: {job_id} -> cluster={cluster_id}, worker={cluster.worker_id}")
        
        return DispatchResult(
            success=True,
            job_id=job_id,
            cluster_id=cluster_id,
            worker_id=cluster.worker_id,
        )
    
    def start_job_execution(self, job_id: str) -> bool:
        """
        开始执行 Job
        
        Args:
            job_id: Job ID
            
        Returns:
            是否成功
        """
        cluster_id = self._job_cluster.get(job_id)
        if not cluster_id:
            return False
        
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            return False
        
        # 更新 Job 状态
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.RUNNING
        
        return cluster.start_running(job_id)
    
    # ===== Job 完成 =====
    
    def complete_job(self, job_id: str, result: Optional[str] = None) -> bool:
        """
        完成 Job
        
        Args:
            job_id: Job ID
            result: 执行结果 (可选)
            
        Returns:
            是否成功
        """
        cluster_id = self._job_cluster.get(job_id)
        if not cluster_id:
            return False
        
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            return False
        
        # 释放锁
        if not cluster.finish_job(job_id):
            return False
        
        # 更新 Job 状态
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            if result:
                job.result = result
        
        # 清理映射
        self._cluster_jobs.pop(cluster_id, None)
        self._job_cluster.pop(job_id, None)
        
        logger.info(f"Job completed on slot {cluster_id}")
        
        return True
    
    def fail_job(self, job_id: str, reason: str) -> bool:
        """
        标记 Job 失败
        
        Args:
            job_id: Job ID
            reason: 失败原因
            
        Returns:
            是否成功
        """
        cluster_id = self._job_cluster.get(job_id)
        if not cluster_id:
            return False
        
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            return False
        
        # 释放锁
        cluster.release_lock(job_id)
        
        # 更新 Job 状态
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.FAILED
            job.retry_count += 1
        
        # 清理映射
        self._cluster_jobs.pop(cluster_id, None)
        self._job_cluster.pop(job_id, None)
        
        logger.warning(f"Job failed: {job_id}, reason={reason}")
        
        return True
    
    # ===== Pre-Lock 回调 =====
    
    def _on_pre_lock_confirmed(self, job_id: str, cluster_id: str) -> None:
        """Pre-Lock 确认回调"""
        logger.info(f"Pre-Lock confirmed: job={job_id}, slot={cluster_id}")
    
    def _on_pre_lock_expired(self, job_id: str, cluster_id: str) -> None:
        """Pre-Lock 过期回调"""
        logger.warning(f"Pre-Lock expired: job={job_id}, slot={cluster_id}")
        # 触发重新匹配
        self._job_cluster.pop(job_id, None)
    
    def _on_pre_lock_rejected(self, job_id: str, cluster_id: str, reason: str) -> None:
        """Pre-Lock 拒绝回调"""
        logger.warning(f"Pre-Lock rejected: job={job_id}, slot={cluster_id}, reason={reason}")
        self._job_cluster.pop(job_id, None)
    
    # ===== Slot Pool 操作 =====
    
    def poll_slot(self, cluster_id: str) -> Optional[Job]:
        """Slot 主动拉取 Job
        
        Args:
            cluster_id: Slot ID
            
        Returns:
            Job 或 None
        """
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            logger.warning(f"Slot not found: {cluster_id}")
            return None
        
        if cluster.status not in [SlotStatus.FREE, SlotStatus.PARTIALLY_RESERVED]:
            logger.debug(f"Slot {cluster_id} not free (status: {cluster.status})")
            return None
        
        # 检查容量
        if not cluster.is_available():
            return None
        
        # 从 Order Book 获取候选 Jobs
        candidate_jobs = self.order_book.get_all_jobs()
        if not candidate_jobs:
            return None
        
        # 按优先级和创建时间排序
        candidate_jobs.sort(key=lambda j: (-j.priority, j.created_at))
        
        # 尝试匹配
        for job in candidate_jobs:
            # Hard Filter
            passed, _ = self.hard_filter.filter(cluster, job)
            if not passed:
                continue
            
            # 尝试 Pre-Lock
            pre_lock_result = self.pre_lock.request_pre_lock(job.job_id, slot)
            if pre_lock_result.success:
                ack_result = self.pre_lock.receive_ack(job.job_id, slot)
                if ack_result.success:
                    # 更新 Job
                    job.cluster_id = cluster.cluster_id
                    job.node_id = cluster.node_id
                    job.worker_id = cluster.worker_id
                    job.status = JobStatus.MATCHED
                    
                    # 从 Order Book 移除
                    self.order_book.remove_job(job.job_id)
                    self._job_slot[job.job_id] = cluster.cluster_id
                    
                    logger.info(f"Slot {cluster_id} polled job: {best_job.job_id} (score: {best_score:.3f})")
                    return job
        
        return None
    
    def release_slot(self, cluster_id: str) -> bool:
        """释放 Slot (slot 主动释放资源)
        
        Args:
            cluster_id: Slot ID
            
        Returns:
            是否成功
        """
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            return False
        
        job_id = self._cluster_jobs.get(cluster_id)
        
        if job_id:
            cluster.release_lock(job_id)
            job = self.get_job(job_id)
            if job:
                job.status = JobStatus.RELEASED
        
        logger.info(f"Slot {cluster_id} reset to FREE")
        
        return True
    
    def reset_slot(self, cluster_id: str) -> bool:
        """重置 Slot 到初始状态"""
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            return False
        
        cluster.reset_to_free()
        
        # 清理所有关联的 Job 映射
        for job_id in list(self._job_cluster.keys()):
            if self._job_slot[job_id] == cluster_id:
                self._job_cluster.pop(job_id)
        
        self._cluster_jobs.pop(cluster_id, None)
        
        return True
    
    # ===== 统计 =====
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        total_slots = len(self._slots)
        available_slots = sum(1 for s in self._slots.values() if s.is_available())
        pending_jobs = len(self.order_book.get_all_jobs())
        
        return {
            "total_slots": total_slots,
            "available_slots": available_slots,
            "pending_jobs": pending_jobs,
            "active_matches": len(self._matches),
            "cluster_utilization": (total_slots - available_slots) / max(1, total_slots),
        }
