"""
Scoring Function - F3.5: 评分函数
来源: Function/F3-Match-Engine-2.0 Section F3.5

Dynamic Configuration: Weights loaded from config/models.yaml via ScoringConfig
动态配置：权重通过 ScoringConfig 从 config/models.yaml 加载
"""

from typing import Optional
from dataclasses import dataclass

from ..models.cluster import Cluster
from ..models.job import Job
from ..services.compatibility import CompatibilityMatrix, compatibility_matrix
from ..services.scoring_config import ScoringConfig, scoring_config


@dataclass
class ScoreBreakdown:
    """评分明细 / Score Breakdown"""
    price_score: float      # 价格评分 (0-1)
    latency_score: float    # 延迟评分 (0-1)
    load_score: float       # 负载评分 (0-1)
    reputation_score: float # 信誉评分 (0-1)
    compatibility_score: float  # 兼容性评分 (0-1)
    total_score: float      # 总分 (0-1)


class ScoringFunction:
    """
    评分函数 - 综合多个维度计算 Slot-Job 匹配得分
    
    评分公式 (从 config/models.yaml 动态加载):
    Score = price_weight * PriceScore 
          + latency_weight * LatencyScore 
          + load_weight * LoadScore 
          + reputation_weight * ReputationScore 
          + compatibility_weight * CompatibilityScore
    
    默认权重:
    - price: 30%
    - latency: 25%
    - load: 15%
    - reputation: 15%
    - compatibility: 15%
    """
    
    def __init__(
        self,
        compatibility: Optional[CompatibilityMatrix] = None,
        scoring_config: Optional[ScoringConfig] = None,
        # Deprecated: Use scoring_config instead
        price_weight: Optional[float] = None,
        latency_weight: Optional[float] = None,
        load_weight: Optional[float] = None,
        reputation_weight: Optional[float] = None,
        compatibility_weight: Optional[float] = None,
    ):
        from ..services.scoring_config import scoring_config as _scoring_config_singleton
        
        self.compatibility = compatibility or compatibility_matrix
        
        # Load weights from config (with optional override)
        # 从配置加载权重（可选覆盖）
        self._scoring_config = scoring_config or _scoring_config_singleton
        
        # Use provided weights if given, otherwise load from config
        # 如果提供了权重则使用，否则从配置加载
        self.price_weight = (
            price_weight 
            if price_weight is not None 
            else self._scoring_config.price_weight
        )
        self.latency_weight = (
            latency_weight 
            if latency_weight is not None 
            else self._scoring_config.latency_weight
        )
        self.load_weight = (
            load_weight 
            if load_weight is not None 
            else self._scoring_config.load_weight
        )
        self.reputation_weight = (
            reputation_weight 
            if reputation_weight is not None 
            else self._scoring_config.reputation_weight
        )
        self.compatibility_weight = (
            compatibility_weight 
            if compatibility_weight is not None 
            else self._scoring_config.compatibility_weight
        )
    
    def calculate(self, cluster: Cluster, job: Job) -> float:
        """计算综合评分"""
        breakdown = self.get_breakdown(cluster, job)
        return breakdown.total_score
    
    def get_breakdown(self, cluster: Cluster, job: Job) -> ScoreBreakdown:
        """获取评分明细"""
        # 1. Price Score (越低越好)
        price_score = self._calc_price_score(cluster, job)
        
        # 2. Latency Score (越低越好)
        latency_score = self._calc_latency_score(cluster, job)
        
        # 3. Load Score (剩余容量越多越好)
        load_score = self._calc_load_score(cluster)
        
        # 4. Reputation Score
        reputation_score = self._calc_reputation_score(cluster)
        
        # 5. Compatibility Score
        compatibility_score = self._calc_compatibility_score(cluster, job)
        
        # 综合评分
        total_score = (
            self.price_weight * price_score +
            self.latency_weight * latency_score +
            self.load_weight * load_score +
            self.reputation_weight * reputation_score +
            self.compatibility_weight * compatibility_score
        )
        
        return ScoreBreakdown(
            price_score=price_score,
            latency_score=latency_score,
            load_score=load_score,
            reputation_score=reputation_score,
            compatibility_score=compatibility_score,
            total_score=total_score,
        )
    
    def _calc_price_score(self, cluster: Cluster, job: Job) -> float:
        """计算价格评分 (0-1，越高越好)"""
        # 归一化: 如果 cluster 价格 <= job 出价，得满分 1.0
        # 如果 cluster 价格 > job 出价，扣分
        if cluster.pricing.output_price <= job.bid_price:
            return 1.0
        
        # 价格超出越多，扣分越多（最低 0）
        ratio = job.bid_price / max(cluster.pricing.output_price, 0.001)
        return max(0.0, ratio)
    
    def _calc_latency_score(self, cluster: Cluster, job: Job) -> float:
        """计算延迟评分 (0-1，越高越好)"""
        # 归一化: 如果 cluster 延迟 <= job 最大延迟，得满分 1.0
        if cluster.performance.avg_latency_ms <= job.max_latency:
            return 1.0
        
        # 延迟超出越多，扣分越多
        ratio = job.max_latency / max(cluster.performance.avg_latency_ms, 1)
        return max(0.0, ratio)
    
    def _calc_load_score(self, cluster: Cluster) -> float:
        """计算负载评分 (0-1，剩余容量越多越好)"""
        if cluster.capacity.max_concurrency <= 0:
            return 0.0
        
        remaining = cluster.capacity.available_capacity
        return remaining / cluster.capacity.max_concurrency
    
    def _calc_reputation_score(self, cluster: Cluster) -> float:
        """计算信誉评分 (0-1)"""
        return cluster.performance.success_rate
    
    def _calc_compatibility_score(self, cluster: Cluster, job: Job) -> float:
        """计算兼容性评分 (0-1)"""
        job_model = job.model_requirement
        cluster_model = cluster.model.name
        return self.compatibility.get_compatibility(job_model, cluster_model)
    
    def rank_clusters(self, clusters: list[Cluster], job: Job) -> list[tuple[Cluster, float]]:
        """对 Clusters 按评分排序（降序）"""
        scored = [(cluster, self.calculate(cluster, job)) for cluster in clusters]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
    
    # 别名兼容
    def rank_slots(self, clusters: list[Cluster], job: Job) -> list[tuple[Cluster, float]]:
        """对 Slots 按评分排序（降序）(兼容别名)"""
        return self.rank_clusters(clusters, job)


# 全局实例
scoring_function = ScoringFunction()
