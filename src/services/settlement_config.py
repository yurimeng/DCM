"""
Settlement Configuration Service
结算配置服务 - 统一管理结算相关配置
(Unified settlement configuration management)
"""

import os
import yaml
from typing import Dict, Optional


class SettlementConfig:
    """
    Settlement Configuration Manager (Dynamic Loading)
    结算配置管理器（动态加载）
    
    Loads configuration from config/models.yaml
    从配置文件动态加载结算参数
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
        config_path = os.environ.get(
            "DCM_MODEL_CONFIG",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "models.yaml")
        )
        
        # Try multiple paths
        paths_to_try = [
            config_path,
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "models.yaml"),
            "/Users/yurimeng/Code/Platform/DCM/config/models.yaml",
        ]
        
        for path in paths_to_try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self._config = yaml.safe_load(f)
                return
        
        # Fallback to default config
        self._config = self._get_default_config()
    
    def _get_default_config(self) -> Dict:
        """Get default configuration / 获取默认配置"""
        return {
            "settlement": {
                "platform_fee_rate": 0.05,
                "node_earn_rate": 0.95,
                "escrow": {
                    "buffer_multiplier": 1.1,
                    "min_bid_price": 0.0001,
                },
                "latency_threshold_good": 5000,
                "latency_threshold_mild": 10000,
                "similarity_threshold_high": 0.85,
                "similarity_threshold_low": 0.65,
                "layer2_sample_rate": 0.1,
            },
            "stake": {
                "personal": 50.0,
                "professional": 200.0,
                "enterprise": 1000.0,
            }
        }
    
    @property
    def settlement_config(self) -> Dict:
        """Get settlement config section / 获取结算配置段"""
        return self._config.get("settlement", {})
    
    @property
    def stake_config(self) -> Dict:
        """Get stake config section / 获取 Stake 配置段"""
        return self._config.get("stake", {})
    
    # ===== Settlement Rates =====
    # 结算比例
    
    @property
    def platform_fee_rate(self) -> float:
        """
        Platform fee rate (e.g., 0.05 = 5%)
        平台手续费比例
        """
        return self.settlement_config.get("platform_fee_rate", 0.05)
    
    @property
    def node_earn_rate(self) -> float:
        """
        Node earning rate (e.g., 0.95 = 95%)
        节点收入比例
        """
        return self.settlement_config.get("node_earn_rate", 0.95)
    
    # ===== Escrow Configuration =====
    # Escrow 配置
    
    @property
    def escrow_buffer_multiplier(self) -> float:
        """
        Escrow locked amount multiplier
        Escrow 锁定金额倍数
        """
        return self.settlement_config.get("escrow", {}).get("buffer_multiplier", 1.1)
    
    @property
    def escrow_auto_complete_seconds(self) -> int:
        """
        Auto-complete delay in seconds after job completion
        Job 完成后自动完成的延迟秒数
        """
        return self.settlement_config.get("escrow", {}).get("auto_complete_seconds", 60)
    
    @property
    def escrow_allow_cancellation(self) -> bool:
        """
        Allow cancellation before auto-complete
        允许在自动完成前取消
        """
        return self.settlement_config.get("escrow", {}).get("allow_cancellation", True)
    
    @property
    def min_bid_price(self) -> float:
        """
        Minimum bid price (USDC/1M tokens)
        最小报价
        """
        return self.settlement_config.get("escrow", {}).get("min_bid_price", 0.0001)
    
    # ===== Verification Thresholds =====
    # 验证阈值
    
    @property
    def layer2_sample_rate(self) -> float:
        """
        Layer 2 verification sample rate (10% default)
        Layer 2 抽样比例
        """
        return self.settlement_config.get("layer2_sample_rate", 0.1)
    
    @property
    def latency_threshold_good(self) -> int:
        """
        Good latency threshold in milliseconds
        良好延迟阈值 (ms)
        """
        return self.settlement_config.get("latency_threshold_good", 5000)
    
    @property
    def latency_threshold_mild(self) -> int:
        """
        Acceptable latency threshold in milliseconds
        可接受延迟阈值 (ms)
        """
        return self.settlement_config.get("latency_threshold_mild", 10000)
    
    @property
    def similarity_threshold_high(self) -> float:
        """
        High similarity threshold (for excellent quality)
        高相似度阈值
        """
        return self.settlement_config.get("similarity_threshold_high", 0.85)
    
    @property
    def similarity_threshold_low(self) -> float:
        """
        Low similarity threshold (for passing quality)
        低相似度阈值
        """
        return self.settlement_config.get("similarity_threshold_low", 0.65)
    
    # ===== Stake Configuration =====
    # Stake 配置
    
    @property
    def stake_personal(self) -> float:
        """
        Personal node stake threshold
        个人节点 Stake 门槛
        """
        return self.stake_config.get("personal", 50.0)
    
    @property
    def stake_professional(self) -> float:
        """
        Professional node stake threshold
        专业节点 Stake 门槛
        """
        return self.stake_config.get("professional", 200.0)
    
    @property
    def stake_enterprise(self) -> float:
        """
        Enterprise node stake threshold
        企业节点 Stake 门槛
        """
        return self.stake_config.get("enterprise", 1000.0)
    
    # ===== Calculation Methods =====
    # 计算方法
    
    def calculate_platform_fee(self, actual_cost: float) -> float:
        """
        Calculate platform fee from actual cost
        根据实际费用计算平台手续费
        """
        return actual_cost * self.platform_fee_rate
    
    def calculate_node_earn(self, actual_cost: float) -> float:
        """
        Calculate node earnings from actual cost
        根据实际费用计算节点收入
        """
        return actual_cost * self.node_earn_rate
    
    def calculate_escrow_locked(
        self,
        bid_price: float,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """
        Calculate escrow locked amount
        计算 Escrow 锁定金额 (bid_price: USDC per token)
        
        Formula: locked = bid_price * (input + output) * buffer_multiplier
        """
        total_tokens = input_tokens + output_tokens
        base_cost = bid_price * total_tokens  # per-token 直接计算
        return base_cost * self.escrow_buffer_multiplier
    
    def calculate_settlement(
        self,
        actual_cost: float,
        bid_price: float,
        actual_latency_ms: int
    ) -> Dict[str, float]:
        """
        Calculate complete settlement with penalty if applicable
        计算完整结算（包含可能的降级惩罚）
        """
        # Base settlement
        platform_fee = self.calculate_platform_fee(actual_cost)
        node_earn = self.calculate_node_earn(actual_cost)
        
        # Check for degraded settlement
        settlement_type = "normal"
        penalty_rate = 1.0
        
        if actual_latency_ms > self.latency_threshold_mild:
            settlement_type = "degraded"
            penalty_rate = 0.5  # 50% penalty
            node_earn = node_earn * penalty_rate
            platform_fee = platform_fee * penalty_rate
        
        return {
            "actual_cost": actual_cost,
            "platform_fee": platform_fee,
            "node_earn": node_earn,
            "settlement_type": settlement_type,
            "penalty_rate": penalty_rate,
        }
    
    def reload(self):
        """Reload configuration from file / 重新加载配置文件"""
        self._load_config()


# Global singleton instance
settlement_config = SettlementConfig()
