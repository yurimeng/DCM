"""
Matching Service - F3: 撮合引擎
来源: PRD 0.2 Section 5.1 & Function/F3

v3.2: 与 Job Queue 解耦，通过依赖注入使用 JobQueueService
"""

from typing import Optional, List
from datetime import datetime
import logging

from .queue import JobQueueService, create_queue
from ..models import Job, Node, Match, JobStatus, NodeStatus
from config import settings

logger = logging.getLogger(__name__)


class MatchingService:
    """
    撮合引擎服务
    
    职责:
    - 消费 Job Queue 中的 Job
    - 匹配 Node Slot
    - 创建 Match 记录
    
    注意: 
    - 与 Job Queue 完全解耦，通过注入的 queue 服务消费
    - 不直接管理 Job 存储，只负责撮合逻辑
    """
    
    def __init__(self, queue: Optional[JobQueueService] = None):
        """
        初始化撮合服务
        
        Args:
            queue: Job 队列服务 (注入依赖)
                   如果为 None，使用全局单例
        """
        # 依赖注入
        self._queue = queue
        
        # 内存存储（Node、Match 和本地 Pending Jobs）
        self._online_nodes: dict[str, Node] = {}
        self._pending_jobs: dict[str, Job] = {}  # 本地待撮合队列（向后兼容）
        self._matches: dict[str, Match] = {}
        self._job_to_match: dict[str, str] = {}  # job_id -> match_id
        self._node_jobs: dict[str, str] = {}  # node_id -> match_id
    
    @property
    def queue(self) -> JobQueueService:
        """获取 Job Queue (懒加载，自动根据配置选择)"""
        if self._queue is None:
            self._queue = create_queue()  # 读取配置: in_memory=true → InMemory, false → Redis
        return self._queue
    
    def add_job(self, job: Job) -> str:
        """
        添加 Job 到队列 (通过 Job Queue)
        
        Args:
            job: Job 对象
        
        Returns:
            job_id
        """
        # 入队到 Job Queue
        job_data = job.model_dump()
        # 添加兼容字段 model (InMemoryQueue 检查 model 或 model_requirement)
        job_data["model"] = job.model
        self._pending_jobs[job.job_id] = job  # 同时保存在本地（向后兼容）
        return self.queue.enqueue(job_data)
    
    def remove_job(self, job_id: str) -> None:
        """从队列移除 Job"""
        self._pending_jobs.pop(job_id, None)  # 从本地队列移除
    
    def register_node(self, node: Node) -> None:
        """注册节点"""
        self._online_nodes[node.node_id] = node
    
    def update_node_status(self, node_id: str, status: NodeStatus) -> None:
        """更新节点状态"""
        if node_id in self._online_nodes:
            self._online_nodes[node_id].status = status
    
    def unregister_node(self, node_id: str) -> None:
        """注销节点"""
        self._online_nodes.pop(node_id, None)
    
    def trigger_match(self, job_id: str) -> Optional[Match]:
        """
        触发撮合（Job 提交时调用）
        
        优先从本地 _pending_jobs 查找（向后兼容）
        如果找不到，尝试从 Job Queue 获取
        """
        # 先从本地队列查找
        job = self._pending_jobs.get(job_id)
        if job:
            match = self._match(job)
            if match:
                # 从本地队列移除
                self.remove_job(job_id)
                # 从 Job Queue 中移除（标记为已处理）
                self.queue.acknowledge(job_id)
                return match
        return None
    
    def consume_queue(self, timeout: float = 1.0) -> Optional[Match]:
        """
        从 Job Queue 消费 Job 并撮合
        
        Args:
            timeout: 出队等待时间
        
        Returns:
            Match 或 None
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
        """
        节点拉取时触发撮合
        
        从 NodeStatusStore 读取节点状态，而不是本地注册
        """
        # 查找该节点是否已被匹配
        if node_id in self._node_jobs:
            match_id = self._node_jobs[node_id]
            return self._matches.get(match_id)
        
        # 从 NodeStatusStore 检查节点是否在线（10秒内有更新）
        from .node_status_store import node_status_store
        if not node_status_store.is_online(node_id, max_age_seconds=10):
            return None
        
        # 获取节点信息（从 DB 或内存）
        node = self._online_nodes.get(node_id)
        if not node:
            # 节点不在内存中，无法匹配
            return None
        
        # 从 Queue 获取待匹配 Jobs
        pending_jobs_data = self.queue.get_pending_jobs()
        
        if not pending_jobs_data:
            return None
        
        # 分离：通用任务 和 指定模型任务
        generic_jobs = []
        model_jobs = []
        
        for job_data in pending_jobs_data:
            job = Job(**job_data)
            if not job.model:
                generic_jobs.append(job)
            else:
                model_jobs.append(job)
        
        # 1. 先处理指定模型的 Jobs（精确匹配）
        for job in model_jobs:
            if self._can_match(job, node):
                match = self._create_match(job, node)
                if match:
                    # 确认消费
                    self.queue.acknowledge(job.job_id)
                    return match
        
        # 2. 再处理通用 Jobs（使用最优节点）
        if generic_jobs:
            # 对通用任务进行排序：优先选择价格低、速度快、成功率高
            sorted_generic = sorted(
                generic_jobs,
                key=lambda j: (-self._get_match_score(j, node), j.created_at)
            )
            for job in sorted_generic:
                if self._can_match(job, node):
                    match = self._create_match(job, node)
                    if match:
                        # 确认消费
                        self.queue.acknowledge(job.job_id)
                        return match
        
        return None
    
    def get_match(self, match_id: str) -> Optional[Match]:
        """获取 Match"""
        return self._matches.get(match_id)
    
    def get_match_by_job(self, job_id: str) -> Optional[Match]:
        """根据 Job ID 获取 Match"""
        match_id = self._job_to_match.get(job_id)
        return self._matches.get(match_id) if match_id else None
    
    def get_node_prelock_jobs(self, node_id: str) -> List[Job]:
        """
        获取节点的 Pre-lock Jobs
        
        通过 node_id 查找对应的 Match，再获取 Match 的 Job
        """
        prelock_jobs = []
        
        # 遍历所有 matches，找到该节点匹配的 jobs
        for match_id, match in self._matches.items():
            if match.node_id == node_id:
                job_id = match.job_id
                # 从 Queue 获取
                pending = self.queue.get_pending_jobs()
                for job_data in pending:
                    if job_data.get("job_id") == job_id:
                        job = Job(**job_data)
                        if job.status == JobStatus.PRE_LOCKED:
                            prelock_jobs.append(job)
                        break
        
        return prelock_jobs
    
    def _match(self, job: Job) -> Optional[Match]:
        """
        执行撮合逻辑
        
        撮合条件（全部满足）:
        - job.bid_price <= node.ask_price
        - node.avg_latency <= job.max_latency
        - node.status == "online"
        - node.model_support contains job.model
        """
        # 筛选可用节点
        candidates = [
            n for n in self._online_nodes.values()
            if n.status == NodeStatus.ONLINE
            and self._can_match(job, n)
        ]
        
        if not candidates:
            return None
        
        # 策略：最低 ask_price 优先，同价延迟最低优先
        candidates.sort(key=lambda n: (n.ask_price, n.avg_latency))
        
        node = candidates[0]
        return self._create_match(job, node)
    
    def _can_match(self, job: Job, node: Node) -> bool:
        """检查是否可以撮合 (DCM v3.2)
        
        匹配条件（必须全部满足）：
        1. 模型匹配：job.model in node.model_support (如果不指定模型则跳过)
        2. 价格匹配：job.bid_price <= node.ask_price
        3. 延迟匹配：node.avg_latency <= job.max_latency
        4. 队列匹配：node.available_queue >= job_tokens (DCM v3.2)
        
        注意：节点在线状态由 NodeStatusStore 统一管理（poll_node 已检查）
        """
        # 1. 模型匹配
        #    - 如果 job.model 有值 → 必须匹配
        #    - 如果 job.model 为空 → 通用任务，任何模型都可以
        if job.model and job.model not in node.model_support:
            return False
        
        # 2. 价格匹配
        # Job 的出价必须 >= Node 的要价，否则无法成交
        if job.bid_price < node.ask_price:
            return False
        
        # 3. 延迟匹配
        if node.avg_latency > job.max_latency:
            return False
        
        # 4. 队列容量检查
        job_tokens = job.input_tokens + job.output_tokens_limit
        if not node.is_idle():
            return False
        if not node.queue_info.reserve(job_tokens):
            return False
        # 释放预留（实际预留会在 create_match 中处理）
        node.queue_info.release(job_tokens)
        
        return True
    
    def _get_job_tokens(self, job: Job) -> int:
        """计算 Job 需要的 token 数 (DCM v3.2)"""
        return job.input_tokens + job.output_tokens_limit

    def _get_match_score(self, job: Job, node: Node) -> float:
        """计算匹配得分（用于通用任务选择最优节点）
        
        分数越低越优先：
        - 价格权重 50%
        - 延迟权重 30%
        - 成功率权重 20%
        """
        # 归一化价格 (0-1)
        price_score = node.ask_price / max(job.bid_price, 0.001)
        
        # 归一化延迟 (0-1)
        latency_score = job.max_latency / max(node.avg_latency, 1)
        
        # 成功率分数 (0-1)
        success_score = node.avg_success_rate
        
        # 综合得分 (越低越优)
        return price_score * 0.5 + latency_score * 0.3 + success_score * 0.2
    
    def _create_match(self, job: Job, node: Node) -> Match:
        """创建 Match (DCM v3.2)
        
        会在创建 Match 时预留队列容量
        """
        # 锁定价格（快照）- 使用节点的要价 (node.ask_price)
        # 如果 job 出价更高，按 node.ask_price 结算，差额退还给 buyer
        locked_price = node.ask_price
        
        # 确定实际使用的模型
        # - 如果 job 指定了 model → 使用该 model
        # - 如果 job 未指定 model → 使用节点支持的第一个模型（最便宜/最快）
        used_model = job.model if job.model else (node.model_support[0] if node.model_support else None)
        
        # 预留队列容量 (DCM v3.2)
        job_tokens = self._get_job_tokens(job)
        node.queue_info.reserve(job_tokens)
        
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
        
        # 存储
        self._matches[match.match_id] = match
        self._job_to_match[job.job_id] = match.match_id
        self._node_jobs[node.node_id] = match.match_id
        
        logger.info(f"Match created: {match.match_id}, job={job.job_id}, node={node.node_id}, tokens={job_tokens}")
        
        return match
    
    def release_node(self, node_id: str, tokens: int = 0) -> None:
        """释放节点（Job 完成后）(DCM v3.2)
        
        Args:
            node_id: 节点 ID
            tokens: 释放的 token 数量 (从 Job 获取)
        """
        if node_id in self._node_jobs:
            match_id = self._node_jobs[node_id]
            match = self._matches.get(match_id)
            if match:
                # 获取 Job 的 token 数
                job = self._pending_jobs.get(match.job_id)
                if job:
                    tokens = self._get_job_tokens(job)
            
            del self._node_jobs[node_id]
        
        if node_id in self._online_nodes:
            node = self._online_nodes[node_id]
            node.status = NodeStatus.ONLINE
            # 释放队列容量 (DCM v3.2)
            if tokens > 0:
                node.queue_info.release(tokens)
                logger.info(f"Node released: {node_id}, queue released: {tokens}")
    
    def get_pending_jobs_count(self) -> int:
        """获取待撮合 Job 数量（本地队列）"""
        return len(self._pending_jobs)
    
    def get_online_nodes_count(self) -> int:
        """获取在线节点数量"""
        return sum(1 for n in self._online_nodes.values() if n.status == NodeStatus.ONLINE)
    
    def get_queue_stats(self):
        """获取队列统计"""
        return self.queue.get_stats()


# 单例 (使用全局 Job Queue)
matching_service = MatchingService()
