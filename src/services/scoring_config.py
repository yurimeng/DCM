"""
Scoring Configuration Service
评分配置服务 - 统一管理 Match Engine 评分相关配置
(Unified scoring configuration management for Match Engine)
"""

import os
import yaml
from typing import Dict, Optional, Any


class ScoringConfig:
    """
    Scoring Configuration Manager (Dynamic Loading)
    评分配置管理器（动态加载）
    
    Loads configuration from config/models.yaml
    从配置文件动态加载评分参数
    
    Score Formula:
    Score = price_weight * PriceScore 
          + latency_weight * LatencyScore 
          + load_weight * LoadScore 
          + reputation_weight * ReputationScore 
          + compatibility_weight * CompatibilityScore
    """
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """
        Load configuration from YAML file
        从 YAML 文件加载配置
        """
        # Try multiple paths
        paths_to_try = [
            os.environ.get("DCM_MODEL_CONFIG", ""),
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "models.yaml"),
            "/Users/yurimeng/Code/Platform/DCM/config/models.yaml",
        ]
        
        for path in paths_to_try:
            if path and os.path.exists(path):
                with open(path, 'r') as f:
                    self._config = yaml.safe_load(f)
                self._normalize_weights()
                return
        
        # Fallback to default config
        self._config = self._get_default_config()
        self._normalize_weights()
    
    def _normalize_weights(self):
        """
        Ensure weights sum to 1.0
        确保权重总和为 1.0
        """
        weights = self._config.get("scoring", {}).get("weights", {})
        total = sum(weights.values())
        if total != 1.0 and total > 0:
            # Normalize to sum to 1.0
            for key in weights:
                weights[key] = weights[key] / total
            self._config["scoring"]["weights"] = weights
    
    def _get_default_config(self) -> Dict:
        """
        Get default configuration
        获取默认配置
        """
        return {
            "scoring": {
                "weights": {
                    "price": 0.30,
                    "latency": 0.25,
                    "load": 0.15,
                    "reputation": 0.15,
                    "compatibility": 0.15,
                },
                "mode": "weighted",
                "bonuses": {
                    "exact_model_match": 1.0,
                    "low_latency": 1.0,
                    "high_success_rate": 1.0,
                },
                "penalties": {
                    "high_latency": 0.5,
                    "low_capacity": 0.8,
                },
            },
            "compatibility": {
                "scoring_weights": {
                    "exact_match": 1.0,
                    "family_match": 0.8,
                    "compatible": 0.6,
                    "cross_family": 0.3,
                    "invalid": 0.0,
                },
            },
        }
    
    # ===== Scoring Weights =====
    # 评分权重
    
    @property
    def price_weight(self) -> float:
        """
        Price score weight (e.g., 0.30 = 30%)
        价格评分权重
        """
        return self._config.get("scoring", {}).get("weights", {}).get("price", 0.30)
    
    @property
    def latency_weight(self) -> float:
        """
        Latency score weight (e.g., 0.25 = 25%)
        延迟评分权重
        """
        return self._config.get("scoring", {}).get("weights", {}).get("latency", 0.25)
    
    @property
    def load_weight(self) -> float:
        """
        Load score weight (e.g., 0.15 = 15%)
        负载评分权重
        """
        return self._config.get("scoring", {}).get("weights", {}).get("load", 0.15)
    
    @property
    def reputation_weight(self) -> float:
        """
        Reputation score weight (e.g., 0.15 = 15%)
        信誉评分权重
        """
        return self._config.get("scoring", {}).get("weights", {}).get("reputation", 0.15)
    
    @property
    def compatibility_weight(self) -> float:
        """
        Compatibility score weight (e.g., 0.15 = 15%)
        兼容性评分权重
        """
        return self._config.get("scoring", {}).get("weights", {}).get("compatibility", 0.15)
    
    @property
    def weights(self) -> Dict[str, float]:
        """
        All scoring weights as dictionary
        所有评分权重（字典形式）
        """
        return self._config.get("scoring", {}).get("weights", {
            "price": 0.30,
            "latency": 0.25,
            "load": 0.15,
            "reputation": 0.15,
            "compatibility": 0.15,
        })
    
    # ===== Scoring Mode =====
    # 评分模式
    
    @property
    def scoring_mode(self) -> str:
        """
        Scoring mode: "weighted" or "additive"
        评分模式
        """
        return self._config.get("scoring", {}).get("mode", "weighted")
    
    # ===== Bonus/Penalty =====
    # 奖励/惩罚
    
    @property
    def exact_model_match_bonus(self) -> float:
        """
        Exact model match bonus multiplier
        精确模型匹配奖励倍数
        """
        return self._config.get("scoring", {}).get("bonuses", {}).get("exact_model_match", 1.0)
    
    @property
    def low_latency_bonus(self) -> float:
        """
        Low latency bonus multiplier
        低延迟奖励倍数
        """
        return self._config.get("scoring", {}).get("bonuses", {}).get("low_latency", 1.0)
    
    @property
    def high_success_rate_bonus(self) -> float:
        """
        High success rate bonus multiplier
        高成功率奖励倍数
        """
        return self._config.get("scoring", {}).get("bonuses", {}).get("high_success_rate", 1.0)
    
    @property
    def high_latency_penalty(self) -> float:
        """
        High latency penalty multiplier
        高延迟惩罚倍数
        """
        return self._config.get("scoring", {}).get("penalties", {}).get("high_latency", 0.5)
    
    @property
    def low_capacity_penalty(self) -> float:
        """
        Low capacity penalty multiplier
        低容量惩罚倍数
        """
        return self._config.get("scoring", {}).get("penalties", {}).get("low_capacity", 0.8)
    
    # ===== Compatibility Weights =====
    # 兼容性权重
    
    @property
    def compat_exact_match(self) -> float:
        """
        Exact match compatibility score
        精确匹配兼容性评分
        """
        return self._config.get("compatibility", {}).get("scoring_weights", {}).get("exact_match", 1.0)
    
    @property
    def compat_family_match(self) -> float:
        """
        Family match compatibility score
        同系列匹配兼容性评分
        """
        return self._config.get("compatibility", {}).get("scoring_weights", {}).get("family_match", 0.8)
    
    @property
    def compat_compatible(self) -> float:
        """
        Compatible match compatibility score
        兼容匹配兼容性评分
        """
        return self._config.get("compatibility", {}).get("scoring_weights", {}).get("compatible", 0.6)
    
    @property
    def compat_cross_family(self) -> float:
        """
        Cross-family compatibility score
        跨系列兼容性评分
        """
        return self._config.get("compatibility", {}).get("scoring_weights", {}).get("cross_family", 0.3)
    
    @property
    def compat_invalid(self) -> float:
        """
        Invalid/incompatible score
        无效/不兼容评分
        """
        return self._config.get("compatibility", {}).get("scoring_weights", {}).get("invalid", 0.0)
    
    @property
    def compatibility_weights(self) -> Dict[str, float]:
        """
        All compatibility weights as dictionary
        所有兼容性权重（字典形式）
        """
        return self._config.get("compatibility", {}).get("scoring_weights", {
            "exact_match": 1.0,
            "family_match": 0.8,
            "compatible": 0.6,
            "cross_family": 0.3,
            "invalid": 0.0,
        })
    
    # ===== Utility Methods =====
    # 工具方法
    
    def get_weight(self, name: str) -> float:
        """
        Get weight by name
        按名称获取权重
        """
        return getattr(self, f"{name}_weight", 0.0)
    
    def get_compat_score(self, match_type: str) -> float:
        """
        Get compatibility score by match type
        按匹配类型获取兼容性评分
        """
        return getattr(self, f"compat_{match_type}", 0.0)
    
    def reload(self):
        """
        Reload configuration from file
        重新加载配置文件
        """
        self._load_config()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Export configuration as dictionary
        导出配置为字典
        """
        return {
            "scoring": {
                "weights": self.weights,
                "mode": self.scoring_mode,
                "bonuses": self._config.get("scoring", {}).get("bonuses", {}),
                "penalties": self._config.get("scoring", {}).get("penalties", {}),
            },
            "compatibility": {
                "scoring_weights": self.compatibility_weights,
            },
        }
    
    def __repr__(self) -> str:
        """String representation"""
        return f"ScoringConfig(weights={self.weights})"


# Global singleton instance
scoring_config = ScoringConfig()
