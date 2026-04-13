"""
Scoring Function - F3.5: 评分函数
来源: Function/F3-Match-Engine-2.0 Section F3.5
"""

from typing import Optional
from dataclasses import dataclass

from ..models.slot import Slot
from ..models.job import Job
from ..services.compatibility import CompatibilityMatrix, compatibility_matrix


@dataclass
class ScoreBreakdown:
    """评分明细"""
    price_score: float      # 价格评分 (0-1)
    latency_score: float    # 延迟评分 (0-1)
    load_score: float       # 负载评分 (0-1)
    reputation_score: float # 信誉评分 (0-1)
    compatibility_score: float  # 兼容性评分 (0-1)
    total_score: float      # 总分 (0-1)


class ScoringFunction:
    """
    评分函数 - 综合多个维度计算 Slot-Job 匹配得分
    
    评分公式:
    Score = 0.30 * PriceScore 
          + 0.25 * LatencyScore 
          + 0.15 * LoadScore 
          + 0.15 * ReputationScore 
          + 0.15 * CompatibilityScore
    """
    
    # 权重配置
    PRICE_WEIGHT = 0.30
    LATENCY_WEIGHT = 0.25
    LOAD_WEIGHT = 0.15
    REPUTATION_WEIGHT = 0.15
    COMPATIBILITY_WEIGHT = 0.15
    
    def __init__(
        self,
        compatibility: Optional[CompatibilityMatrix] = None,
        price_weight: float = PRICE_WEIGHT,
        latency_weight: float = LATENCY_WEIGHT,
        load_weight: float = LOAD_WEIGHT,
        reputation_weight: float = REPUTATION_WEIGHT,
        compatibility_weight: float = COMPATIBILITY_WEIGHT,
    ):
        self.compatibility = compatibility or compatibility_matrix
        self.price_weight = price_weight
        self.latency_weight = latency_weight
        self.load_weight = load_weight
        self.reputation_weight = reputation_weight
        self.compatibility_weight = compatibility_weight
    
    def calculate(self, slot: Slot, job: Job) -> float:
        """计算综合评分"""
        breakdown = self.get_breakdown(slot, job)
        return breakdown.total_score
    
    def get_breakdown(self, slot: Slot, job: Job) -> ScoreBreakdown:
        """获取评分明细"""
        # 1. Price Score (越低越好)
        price_score = self._calc_price_score(slot, job)
        
        # 2. Latency Score (越低越好)
        latency_score = self._calc_latency_score(slot, job)
        
        # 3. Load Score (剩余容量越多越好)
        load_score = self._calc_load_score(slot)
        
        # 4. Reputation Score
        reputation_score = self._calc_reputation_score(slot)
        
        # 5. Compatibility Score
        compatibility_score = self._calc_compatibility_score(slot, job)
        
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
    
    def _calc_price_score(self, slot: Slot, job: Job) -> float:
        """计算价格评分 (0-1，越高越好)"""
        # 归一化: 如果 slot 价格 <= job 出价，得满分 1.0
        # 如果 slot 价格 > job 出价，扣分
        if slot.pricing.output_price <= job.bid_price:
            return 1.0
        
        # 价格超出越多，扣分越多（最低 0）
        ratio = job.bid_price / max(slot.pricing.output_price, 0.001)
        return max(0.0, ratio)
    
    def _calc_latency_score(self, slot: Slot, job: Job) -> float:
        """计算延迟评分 (0-1，越高越好)"""
        # 归一化: 如果 slot 延迟 <= job 最大延迟，得满分 1.0
        if slot.performance.avg_latency_ms <= job.max_latency:
            return 1.0
        
        # 延迟超出越多，扣分越多
        ratio = job.max_latency / max(slot.performance.avg_latency_ms, 1)
        return max(0.0, ratio)
    
    def _calc_load_score(self, slot: Slot) -> float:
        """计算负载评分 (0-1，剩余容量越多越好)"""
        if slot.capacity.max_concurrency <= 0:
            return 0.0
        
        remaining = slot.capacity.available_capacity
        return remaining / slot.capacity.max_concurrency
    
    def _calc_reputation_score(self, slot: Slot) -> float:
        """计算信誉评分 (0-1)"""
        return slot.performance.success_rate
    
    def _calc_compatibility_score(self, slot: Slot, job: Job) -> float:
        """计算兼容性评分 (0-1)"""
        job_model = job.model_requirement
        slot_model = slot.model.name
        return self.compatibility.get_compatibility(job_model, slot_model)
    
    def rank_slots(self, slots: list[Slot], job: Job) -> list[tuple[Slot, float]]:
        """对 Slots 按评分排序（降序）"""
        scored = [(slot, self.calculate(slot, job)) for slot in slots]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


# 全局实例
scoring_function = ScoringFunction()
