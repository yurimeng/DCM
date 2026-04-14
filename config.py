"""
DCM - Decentralized Compute Market
Configuration Settings
"""

import os
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """应用配置"""
    
    # ===== 项目信息 =====
    project_name: str = "DCM"
    version: str = "0.1.0"
    mvp_mode: bool = True
    debug: bool = False  # Debug 模式: 返回详细错误信息
    
    # ===== 数据库 =====
    database_url: str = "sqlite:///./dcm.db"
    database_path: str = "/app/data/dcm.db"
    
    # ===== API 配置 =====
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    
    # ===== 模型限制（MVP）=====
    mvp_model: str = "qwen2.5:7b"
    max_output_tokens: int = 256
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
    similarity_threshold_high: float = 0.85
    similarity_threshold_low: float = 0.65
    node_lock_threshold: int = 3
    
    # ===== 延迟配置 =====
    latency_buffer_multiplier: float = 1.5
    mild_latency_penalty: float = 0.7
    
    # ===== 节点配置 =====
    heartbeat_timeout_seconds: int = 30
    max_retry_count: int = 2
    
    # ===== Node Status Store 配置 =====
    # 可选值: "memory" 或 "redis"
    node_status_store_backend: str = "memory"
    node_status_store_ttl_seconds: int = 30
    
    # ===== Stake 分级 =====
    stake_personal: float = 50.0
    stake_professional: float = 200.0
    stake_datacenter: float = 1000.0
    
    # ===== CORS =====
    allowed_origins: List[str] = ["*"]
    
    class Config:
        env_file = ".env"
        env_prefix = "DCM_"


settings = Settings()


# === Sprint 5: 链上集成配置 ===

# 区块链网络
ETH_RPC_URL = os.getenv("ETH_RPC_URL", "https://polygon-amoy.g.alchemy.com/v2/HFW7npG7zuRpfXz45BF6b")
CHAIN_ID = int(os.getenv("CHAIN_ID", "80002"))
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

# 合约地址
ESCROW_CONTRACT_ADDRESS = os.getenv("ESCROW_CONTRACT_ADDRESS", "0x82B3e998519a6cFaF3a8bA18Ed4d45D5e33Ab368")
STAKE_CONTRACT_ADDRESS = os.getenv("STAKE_CONTRACT_ADDRESS", "")

# USDC 地址 (Polygon Amoy)
USDC_ADDRESS = os.getenv("USDC_ADDRESS", "0x41e94eb3dc53f2dAA30810D49FbA6DeF10Ba27e5")

# 链上模式开关
USE_BLOCKCHAIN = os.getenv("USE_BLOCKCHAIN", "false").lower() == "true"
SYSTEM_ADDRESS = os.getenv("SYSTEM_ADDRESS", "0x0000000000000000000000000000000000000000")
