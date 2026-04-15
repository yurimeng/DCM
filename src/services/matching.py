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
    - 匹配 Node（从 NodeStatusStore 读取节点状态）
    - 创建 Match 记录
    
    注意: 
    - Node 状态从 NodeStatusStore 读取，不维护本地列表
    - 只维护 Match 记录
    """
    
    def __init__(self, queue: Optional[JobQueueService] = None):
        """
        初始化撮合服务
        
        Args:
            queue: Job 队列服务 (注入依赖)
        """
        # 依赖注入
        self._queue = queue
        
        # 只维护 Match 记录，不维护 Node 列表
        self._matches: dict[str, Match] = {}
        self._job_to_match: dict[str, str] = {}  # job_id -> match_id
        self._node_jobs: dict[str, str] = {}  # node_id -> match_id
        self._pending_jobs: dict[str, Job] = {}  # 本地待撮合队列
    
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
        
        从 NodeStatusStore 获取节点状态和容量信息
        """
        # 查找该节点是否已被匹配
        if node_id in self._node_jobs:
            match_id = self._node_jobs[node_id]
            return self._matches.get(match_id)
        
        # 从 NodeStatusStore 检查节点是否在线（使用新的 get_node_info API）
        from .node_status_store import get_node_info
        node_info = get_node_info(node_id)
        if not node_info.is_online:
            return None
        
        # 从 NodeStatusStore 获取实时状态
        node_status = node_status_store.get_node_status(node_id)
        
        # 从 DB 获取节点信息
        from ..database import SessionLocal
        from ..repositories import NodeRepository
        db = SessionLocal()
        try:
            node_repo = NodeRepository(db)
            db_node = node_repo.get(node_id)
            if not db_node:
                return None
            
            # 构建 Node 对象（用于匹配检查）
            import json
            runtime_data = json.loads(db_node.runtime) if isinstance(db_node.runtime, str) else {}
            model_support = json.loads(db_node.model_support) if isinstance(db_node.model_support, str) else []
            
            node = Node(
                node_id=db_node.node_id,
                user_id=db_node.user_id,
                runtime=runtime_data or {'type': 'ollama', 'loaded_models': []},
                hardware={'gpu_type': db_node.gpu_type, 'gpu_count': db_node.gpu_count},
                reliability={'avg_latency_ms': db_node.avg_latency, 'success_rate': 0.95, 'quality_score': 0.9},
                pricing={'ask_price_usdc_per_mtoken': db_node.ask_price},
                location={'region': db_node.region},
            )
            # 设置实时容量（从 NodeStatusStore）
            node.state.available_concurrency = node_status.get('available_concurrency', 1)
            node.state.available_queue_tokens = node_status.get('available_queue_tokens', 1500)
        finally:
            db.close()
        
        # 从 Queue 获取待匹配 Jobs
        pending_jobs_data = self.queue.get_pending_jobs()
        if not pending_jobs_data:
            return None
        
        # 分离：通用任务 和 指定模型任务
        # 过滤掉已经匹配的 Job
        generic_jobs = []
        model_jobs = []
        for job_data in pending_jobs_data:
            job = Job(**job_data)
            # 跳过已匹配的 Job
            if job.job_id in self._job_to_match:
                continue
            if not job.model:
                generic_jobs.append(job)
            else:
                model_jobs.append(job)
        
        # 1. 先处理指定模型的 Jobs
        for job in model_jobs:
            if self._can_match(job, node, node_status):
                match = self._create_match(job, node)
                if match:
                    self.queue.acknowledge(job.job_id)
                    return match
        
        # 2. 再处理通用 Jobs
        if generic_jobs:
            sorted_generic = sorted(
                generic_jobs,
                key=lambda j: (-self._get_match_score(j, node), j.created_at)
            )
            for job in sorted_generic:
                if self._can_match(job, node, node_status):
                    match = self._create_match(job, node)
                    if match:
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
        """获取节点的 Pre-lock Jobs"""
        prelock_jobs = []
        for match_id, match in self._matches.items():
            if match.node_id == node_id:
                job_id = match.job_id
                pending = self.queue.get_pending_jobs()
                for job_data in pending:
                    if job_data.get("job_id") == job_id:
                        job = Job(**job_data)
                        if job.status == JobStatus.PRE_LOCKED:
                            prelock_jobs.append(job)
                        break
        return prelock_jobs
    
    def _match(self, job: Job) -> Optional[Match]:
        """执行撮合逻辑（从 NodeStatusStore 获取节点列表）"""
        from .node_status_store import node_status_store
        
        # 从 DB 获取所有在线节点（通过 NodeStatusStore 检查在线状态）
        from ..database import SessionLocal
        from ..repositories import NodeRepository
        import json
        
        db = SessionLocal()
        try:
            node_repo = NodeRepository(db)
            all_nodes = node_repo.list_all()  # 需要实现 list_all
            
            # 筛选在线节点（使用新的 list_online_nodes API）
            from .node_status_store import list_online_nodes
            online_nodes = list_online_nodes(max_age_seconds=10)
            online_node_ids = {n.node_id for n in online_nodes}
            
            candidates = []
            for db_node in all_nodes:
                if db_node.node_id not in online_node_ids:
                    continue
                
                node_status = node_status_store.get_node_status(db_node.node_id)
                
                runtime_data = json.loads(db_node.runtime) if isinstance(db_node.runtime, str) else {}
                model_support = json.loads(db_node.model_support) if isinstance(db_node.model_support, str) else []
                
                node = Node(
                    node_id=db_node.node_id,
                    user_id=db_node.user_id,
                    runtime=runtime_data or {'type': 'ollama', 'loaded_models': []},
                    hardware={'gpu_type': db_node.gpu_type, 'gpu_count': db_node.gpu_count},
                    reliability={'avg_latency_ms': db_node.avg_latency, 'success_rate': 0.95, 'quality_score': 0.9},
                    pricing={'ask_price_usdc_per_mtoken': db_node.ask_price},
                    location={'region': db_node.region},
                )
                node.state.available_concurrency = node_status.get('available_concurrency', 1)
                node.state.available_queue_tokens = node_status.get('available_queue_tokens', 1500)
                
                if self._can_match(job, node, node_status):
                    candidates.append(node)
        finally:
            db.close()
        
        if not candidates:
            return None
        
        # 策略：最低 ask_price 优先
        candidates.sort(key=lambda n: (n.ask_price, n.avg_latency))
        return self._create_match(job, candidates[0])
    
    def _can_match(self, job: Job, node: Node, node_status: dict = None) -> bool:
        """检查是否可以撮合 (从 NodeStatusStore 获取容量)
        
        匹配规则:
        - job.model: 精确匹配 model_support（支持前缀匹配如 qwen → qwen2.5:7b）
        - job.model 为空: 匹配任何可用节点（由系统分配排名第一的）
        """
        # 模型匹配
        if job.model:
            # 检查是否为完整模型名
            if job.model in node.model_support:
                pass  # 精确匹配
            else:
                # 尝试前缀匹配（如 qwen 匹配 qwen2.5:7b）
                family_found = False
                for m in node.model_support:
                    if m.startswith(job.model):
                        family_found = True
                        break
                if not family_found:
                    return False
        # job.model 为空: 不检查模型（匹配任何可用节点）
        
        # 价格匹配
        if job.bid_price < node.ask_price:
            return False
        
        # 3. 延迟匹配
        if node.avg_latency > job.max_latency:
            return False
        
        # 4. 容量检查（从 node_status 获取）
        if node_status:
            available_tokens = node_status.get('available_queue_tokens', 0)
            job_tokens = job.input_tokens + job.output_tokens_limit
            if available_tokens < job_tokens:
                return False
        
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
        
        logger.info(f"Match created: {match.match_id}, job={job.job_id}, node={node.node_id}")
        
        return match
    
    def release_node(self, node_id: str, tokens: int = 0) -> None:
        """释放节点（Job 完成后）
        
        从 _node_jobs 中移除节点映射
        """
        if node_id in self._node_jobs:
            del self._node_jobs[node_id]
            logger.info(f"Node released: {node_id}")
    
    def get_pending_jobs_count(self) -> int:
        """获取待撮合 Job 数量"""
        return len(self.queue.get_pending_jobs())
    
    def get_queue_stats(self):
        """获取队列统计"""
        return self.queue.get_stats()


# 单例 (使用全局 Job Queue)
matching_service = MatchingService()
