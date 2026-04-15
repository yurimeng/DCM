"""
DCM - Decentralized Compute Market
Configuration Settings / 配置设置

This file contains all configuration settings for the DCM application.
本文件包含 DCM 应用的所有配置设置。

环境变量: DCM_* 前缀 (可通过 .env 文件配置)
Environment Variable Prefix: DCM_*
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.constants import (
    TimeConstants,
    QueueConstants,
    VerificationConstants,
    MatchingConstants,
    SettlementConstants,
    ModelConstants,
    StakeConstants,
    PriceConstants,
    NodeStatusStoreConstants,
)


class Settings(BaseSettings):
    """应用配置 / Application Settings"""
    
    # =========================================================================
    # Pydantic V2 配置 / Pydantic V2 Configuration
    # =========================================================================
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DCM_",
        case_sensitive=False,
        extra="ignore",
    )
    
    # =========================================================================
    # 项目信息 / Project Information
    # =========================================================================
    
    project_name: str = "DCM"  # 项目名称 / Project name
    version: str = "0.1.0"  # 版本号 / Version number
    mvp_mode: bool = True  # MVP 模式开关 / MVP mode flag
    debug: bool = True  # 调试模式：返回详细错误信息 / Debug mode: return detailed error messages
    
    # =========================================================================
    # 数据库 / Database
    # =========================================================================
    
    # SQLite 连接字符串 / SQLite connection string
    # 示例 / Example: "sqlite:///./dcm.db"
    database_url: str = "sqlite:///./dcm.db"
    
    # Docker 容器内数据库路径 / Database path inside Docker container
    database_path: str = "/app/data/dcm.db"
    
    # =========================================================================
    # API 配置 / API Configuration
    # =========================================================================
    
    api_host: str = "0.0.0.0"  # API 服务监听地址 / API service listen address
    api_port: int = 8000  # API 服务监听端口 / API service listen port
    api_prefix: str = "/api/v1"  # API 路由前缀 / API route prefix
    
    # =========================================================================
    # 模型限制（MVP）/ Model Limits (MVP)
    # =========================================================================
    
    # MVP 模式下支持的模型 / Supported model in MVP mode
    mvp_model: str = ModelConstants.MVP_MODEL
    
    # 单次请求最大输出 tokens 数 / Maximum output tokens per request
    max_output_tokens: int = ModelConstants.MAX_OUTPUT_TOKENS
    
    # 最大延迟容忍（毫秒）/ Maximum latency tolerance (milliseconds)
    max_latency_ms: int = ModelConstants.MAX_LATENCY_MS
    
    # 最小延迟要求（毫秒）/ Minimum latency requirement (milliseconds)
    min_latency_ms: int = ModelConstants.MIN_LATENCY_MS
    
    # =========================================================================
    # Escrow 配置 / Escrow Configuration
    # =========================================================================
    
    # Escrow 金额缓冲倍数（防止 Gas 费等额外费用）/ Escrow amount buffer multiplier
    # 用于计算 Job 预估成本时的安全边际 / Used as safety margin for estimated job cost
    escrow_buffer: float = SettlementConstants.ESCROW_BUFFER
    
    # 最低出价（USDC/token）/ Minimum bid price (USDC/token)
    min_bid_price: float = PriceConstants.MIN_BID_PRICE
    
    # 默认出价（USDC/token）/ Default bid price (USDC/token)
    # 0.000001 = 1 USDC per 1M tokens
    default_bid_price: float = PriceConstants.DEFAULT_BID_PRICE
    
    # 默认要价（USDC/token）/ Default ask price (USDC/token)
    default_ask_price: float = PriceConstants.DEFAULT_ASK_PRICE
    
    # =========================================================================
    # 结算配置 / Settlement Configuration
    # =========================================================================
    
    # 平台服务费率 / Platform service fee rate
    platform_fee_rate: float = SettlementConstants.PLATFORM_FEE_RATE
    
    # 节点收入分配比例 / Node earnings distribution ratio
    node_earn_rate: float = SettlementConstants.NODE_EARN_RATE
    
    # =========================================================================
    # 验证配置 / Verification Configuration
    # =========================================================================
    
    # Layer2 抽样验证比例 / Layer2 sampling verification rate
    # 0.1 = 10% 的 Job 会被抽样进行 Layer2 验证 / 10% of Jobs will be sampled for Layer2 verification
    layer2_sample_rate: float = VerificationConstants.LAYER2_SAMPLE_RATE
    
    # 高相似度阈值 / High similarity threshold
    # 验证结果相似度 >= 此值视为验证通过 / Verification result similarity >= this value is considered passed
    similarity_threshold_high: float = VerificationConstants.SIMILARITY_THRESHOLD_HIGH
    
    # 低相似度阈值 / Low similarity threshold
    # 验证结果相似度 < 此值视为验证失败 / Verification result similarity < this value is considered failed
    similarity_threshold_low: float = VerificationConstants.SIMILARITY_THRESHOLD_LOW
    
    # 节点锁定阈值 / Node lock threshold
    # 节点连续失败次数达到此值将被锁定 / Node will be locked after consecutive failures reach this value
    node_lock_threshold: int = VerificationConstants.NODE_LOCK_THRESHOLD
    
    # =========================================================================
    # 延迟配置 / Latency Configuration
    # =========================================================================
    
    # 延迟缓冲倍数 / Latency buffer multiplier
    # 用于计算节点是否满足 Job 延迟要求 / Used to calculate if node meets Job latency requirement
    # avg_latency * latency_buffer_multiplier <= job.max_latency
    latency_buffer_multiplier: float = VerificationConstants.LATENCY_BUFFER_MULTIPLIER
    
    # 轻微延迟惩罚系数 / Mild latency penalty coefficient
    # 延迟略微超标的节点会被降低优先级 / Nodes with slightly exceeded latency will be deprioritized
    mild_latency_penalty: float = VerificationConstants.MILD_LATENCY_PENALTY
    
    # =========================================================================
    # 节点配置 / Node Configuration
    # =========================================================================
    
    # 心跳超时时间（秒）/ Heartbeat timeout (seconds)
    # 节点超过此时间未发送心跳视为离线 / Node is considered offline if no heartbeat received after this time
    heartbeat_timeout_seconds: int = TimeConstants.HEARTBEAT_TIMEOUT_SECONDS
    
    # 最大重试次数 / Maximum retry count
    # Job 执行失败后的最大重试次数 / Maximum retry attempts when Job execution fails
    max_retry_count: int = QueueConstants.MAX_RETRIES
    
    # =========================================================================
    # Node Status Store 配置 / Node Status Store Configuration
    # =========================================================================
    
    # 状态存储后端类型 / Status storage backend type
    # 可选值 / Options: "memory" (单机) / "redis" (分布式)
    node_status_store_backend: str = NodeStatusStoreConstants.DEFAULT_BACKEND
    
    # 状态数据 TTL（秒）/ Status data TTL (seconds)
    # Redis 后端有效，内存后端忽略 / Valid for Redis backend, ignored for memory backend
    node_status_store_ttl_seconds: int = NodeStatusStoreConstants.DEFAULT_TTL_SECONDS
    
    # =========================================================================
    # Stake 分级配置 / Stake Tier Configuration
    # =========================================================================
    
    # Personal 级 Stake 金额（USDC）/ Personal tier Stake amount (USDC)
    # 要求：< 4 GPU / Requirement: < 4 GPUs
    stake_personal: float = StakeConstants.STAKE_PERSONAL
    
    # Professional 级 Stake 金额（USDC）/ Professional tier Stake amount (USDC)
    # 要求：4-7 GPU
    stake_professional: float = StakeConstants.STAKE_PROFESSIONAL
    
    # Datacenter 级 Stake 金额（USDC）/ Datacenter tier Stake amount (USDC)
    # 要求：>= 8 GPU
    stake_datacenter: float = StakeConstants.STAKE_DATACENTER
    
    # =========================================================================
    # CORS 配置 / CORS Configuration
    # =========================================================================
    
    # 允许的跨域来源 / Allowed CORS origins
    # 生产环境建议限制具体域名 / In production, restrict to specific domains
    allowed_origins: list[str] = ["*"]


settings = Settings()


# =============================================================================
# Sprint 5: 链上集成配置 / Blockchain Integration Configuration
# =============================================================================

# 区块链网络配置 / Blockchain Network Configuration
ETH_RPC_URL = os.getenv("ETH_RPC_URL", "https://polygon-amoy.g.alchemy.com/v2/HFW7npG7zuRpfXz45BF6b")
CHAIN_ID = int(os.getenv("CHAIN_ID", "80002"))  # Polygon Amoy Chain ID

# 钱包私钥（注意安全！建议使用环境变量或密钥管理服务）/ Wallet private key
# WARNING: 敏感信息，生产环境请使用安全的密钥管理方案
# WARNING: Sensitive info, use secure key management in production
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

# 合约地址配置 / Contract Address Configuration
ESCROW_CONTRACT_ADDRESS = os.getenv("ESCROW_CONTRACT_ADDRESS", "0x82B3e998519a6cFaF3a8bA18Ed4d45D5e33Ab368")
STAKE_CONTRACT_ADDRESS = os.getenv("STAKE_CONTRACT_ADDRESS", "")

# USDC 代币地址（Polygon Amoy）/ USDC Token Address (Polygon Amoy)
USDC_ADDRESS = os.getenv("USDC_ADDRESS", "0x41e94eb3dc53f2dAA30810D49FbA6DeF10Ba27e5")

# 链上模式开关 / Blockchain Mode Switch
# true: 使用链上 Escrow 和 Stake / Use on-chain Escrow and Stake
# false: 使用本地模拟（开发/测试）/ Use local simulation (dev/test)
USE_BLOCKCHAIN = os.getenv("USE_BLOCKCHAIN", "false").lower() == "true"

# 系统地址（用于接收平台手续费）/ System address (for receiving platform fees)
SYSTEM_ADDRESS = os.getenv("SYSTEM_ADDRESS", "0x0000000000000000000000000000000000000000")
