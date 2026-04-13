"""
Matching Service - F3: 撮合引擎
来源: PRD 0.2 Section 5.1 & Function/F3
"""

from typing import Optional, List
from datetime import datetime
from ..models import Job, Node, Match, JobStatus, NodeStatus
from config import settings


class MatchingService:
    """撮合引擎服务"""
    
    def __init__(self):
        # 内存存储（MVP）
        self._pending_jobs: dict[str, Job] = {}
        self._online_nodes: dict[str, Node] = {}
        self._matches: dict[str, Match] = {}
        self._job_to_match: dict[str, str] = {}  # job_id -> match_id
        self._node_jobs: dict[str, str] = {}  # node_id -> match_id
    
    def add_job(self, job: Job) -> None:
        """添加 Job 到待撮合队列"""
        self._pending_jobs[job.job_id] = job
    
    def remove_job(self, job_id: str) -> None:
        """从待撮合队列移除 Job"""
        self._pending_jobs.pop(job_id, None)
    
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
        """
        job = self._pending_jobs.get(job_id)
        if not job:
            return None
        
        return self._match(job)
    
    def poll_node(self, node_id: str) -> Optional[Match]:
        """
        节点拉取时触发撮合
        
        对于通用任务（无 model），优先选择最优节点
        对于指定模型任务，按正常流程匹配
        """
        # 查找该节点是否已被匹配
        if node_id in self._node_jobs:
            match_id = self._node_jobs[node_id]
            return self._matches.get(match_id)
        
        # 获取节点信息
        node = self._online_nodes.get(node_id)
        if not node or node.status != NodeStatus.ONLINE:
            return None
        
        # 获取所有待匹配的 Jobs
        pending_jobs = list(self._pending_jobs.values())
        
        # 分离：通用任务 和 指定模型任务
        generic_jobs = [j for j in pending_jobs if not j.model]
        model_jobs = [j for j in pending_jobs if j.model]
        
        # 1. 先处理指定模型的 Jobs（精确匹配）
        for job in model_jobs:
            if self._can_match(job, node):
                return self._create_match(job, node)
        
        # 2. 再处理通用 Jobs（使用最优节点）
        if generic_jobs:
            # 对通用任务进行排序：优先选择价格低、速度快、成功率高
            sorted_generic = sorted(
                generic_jobs,
                key=lambda j: (-self._get_match_score(j, node), j.created_at)
            )
            for job in sorted_generic:
                if self._can_match(job, node):
                    return self._create_match(job, node)
        
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
                # 在 pending_jobs 中查找
                job = self._pending_jobs.get(job_id)
                if job and job.status == JobStatus.PRE_LOCKED:
                    prelock_jobs.append(job)
        
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
        """检查是否可以撮合
        
        匹配条件（必须全部满足）：
        1. 模型匹配：job.model in node.model_support (如果不指定模型则跳过)
        2. 价格匹配：job.bid_price <= node.ask_price
        3. 延迟匹配：node.avg_latency <= job.max_latency
        4. 节点在线：node.status == NodeStatus.ONLINE
        5. 成功率门槛：node.avg_success_rate >= job.min_success_rate (如果有)
        6. 质量门槛：node.avg_quality_score >= job.min_quality_score (如果有)
        """
        # 1. 模型匹配
        #    - 如果 job.model 有值 → 必须匹配
        #    - 如果 job.model 为空 → 通用任务，任何模型都可以
        if job.model and job.model not in node.model_support:
            return False
        
        # 2. 价格匹配
        if job.bid_price > node.ask_price:
            return False
        
        # 3. 延迟匹配
        if node.avg_latency > job.max_latency:
            return False
        
        # 4. 节点状态
        if node.status != NodeStatus.ONLINE:
            return False
        
        # 5. 成功率检查（可选）
        if hasattr(job, 'min_success_rate') and job.min_success_rate:
            if node.avg_success_rate < job.min_success_rate:
                return False
        
        # 6. 质量评分检查（可选）
        if hasattr(job, 'min_quality_score') and job.min_quality_score:
            if node.avg_quality_score < job.min_quality_score:
                return False
        
        return True

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
        """创建 Match"""
        # 锁定价格（快照）- 使用 job 的 bid_price
        locked_price = job.bid_price
        
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
        
        # 从 pending 队列移除
        self.remove_job(job.job_id)
        
        return match
    
    def release_node(self, node_id: str) -> None:
        """释放节点（Job 完成后）"""
        if node_id in self._node_jobs:
            del self._node_jobs[node_id]
        
        if node_id in self._online_nodes:
            self._online_nodes[node_id].status = NodeStatus.ONLINE
    
    def get_pending_jobs_count(self) -> int:
        """获取待撮合 Job 数量"""
        return len(self._pending_jobs)
    
    def get_online_nodes_count(self) -> int:
        """获取在线节点数量"""
        return sum(1 for n in self._online_nodes.values() if n.status == NodeStatus.ONLINE)


# 单例
matching_service = MatchingService()
