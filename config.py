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
    
    # ===== 数据库 =====
    database_url: str = "sqlite:///./dcm.db"
    database_path: str = "/app/data/dcm.db"
    
    # ===== API 配置 =====
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    
    # ===== 模型限制（MVP）=====
    mvp_model: str = "qwen2.5:7b"
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


# === Sprint 5: 链上集成配置 ===

# 区块链网络
ETH_RPC_URL = os.getenv("ETH_RPC_URL", "https://rpc-mumbai.maticvigil.com")
CHAIN_ID = int(os.getenv("CHAIN_ID", "80001"))  # Polygon Mumbai

# 私钥 (测试用，切勿提交到 GitHub!)
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

# 合约地址 (部署后填写)
ESCROW_CONTRACT_ADDRESS = os.getenv("ESCROW_CONTRACT_ADDRESS", "")
STAKE_CONTRACT_ADDRESS = os.getenv("STAKE_CONTRACT_ADDRESS", "")

# USDC 地址 (Polygon Mumbai)
USDC_ADDRESS = os.getenv("USDC_ADDRESS", "0xe6B8d5cf4c0f8C4d3E3F8E8C3F8E8C3E3F8E8C3E")

# 链上模式开关
USE_BLOCKCHAIN = os.getenv("USE_BLOCKCHAIN", "false").lower() == "true"
