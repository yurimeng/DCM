"""
DCM - Decentralized Compute Market
Configuration Settings
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """应用配置"""
    
    # ===== 项目信息 =====
    project_name: str = "DCM"
    version: str = "0.1.0"
    mvp_mode: bool = True
    
    # ===== 数据库 =====
    database_url: str = "sqlite:///./dcm.db"
    
    # ===== API 配置 =====
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    
    # ===== 模型限制（MVP）=====
    mvp_model: str = "llama3-8b"
    max_output_tokens: int = 4096
    max_latency_ms: int = 30000
    min_latency_ms: int = 1000
    
    # ===== Escrow 配置 =====
    escrow_buffer: float = 1.1  # 1.1x buffer
    min_bid_price: float = 0.0
    
    # ===== 结算配置 =====
    platform_fee_rate: float = 0.05  # 5%
    node_earn_rate: float = 0.95  # 95%
    
    # ===== 验证配置 =====
    layer2_sample_rate: float = 0.1  # 10% 抽样
    similarity_threshold_high: float = 0.85  # > 0.85 一致
    similarity_threshold_low: float = 0.65  # < 0.65 触发复核
    node_lock_threshold: int = 3  # 连续 3 次不一致 → locked
    
    # ===== 延迟配置 =====
    latency_buffer_multiplier: float = 1.5  # max_latency × 1.5
    mild_latency_penalty: float = 0.7  # 降价结算比例
    
    # ===== 节点配置 =====
    heartbeat_timeout_seconds: int = 30
    max_retry_count: int = 2
    
    # ===== Stake 分级 =====
    stake_personal: float = 50.0   # < 24 GB
    stake_professional: float = 200.0  # 24-80 GB
    stake_datacenter: float = 1000.0   # > 80 GB
    
    # ===== 链上配置 =====
    chain_rpc_url: str = ""  # Solana/Base RPC
    escrow_contract_address: str = ""
    stake_contract_address: str = ""
    usdc_mint_address: str = ""
    
    # ===== CORS =====
    allowed_origins: List[str] = ["*"]
    
    class Config:
        env_file = ".env"
        env_prefix = "DCM_"


settings = Settings()
