"""
DCM Constants - 统一管理硬编码常量

所有魔法数字应在此文件中定义，确保：
1. 单一数据源 (Single Source of Truth)
2. 便于维护和修改
3. 类型安全
"""

from enum import Enum
from typing import List


# ===== 时间常量 (秒) =====

class TimeConstants:
    """时间相关常量"""
    HEARTBEAT_TIMEOUT_SECONDS = 30       # 心跳超时
    PRELOCK_TTL_SECONDS = 30             # 预锁定 TTL
    JOB_COMPLETION_GRACE_PERIOD = 60     # Job 完成宽限期
    CLEANUP_INTERVAL_SECONDS = 300        # 清理间隔
    MAX_NODE_OFFLINE_SECONDS = 10        # 节点离线最大间隔


# ===== 队列常量 =====

class QueueConstants:
    """队列相关常量"""
    MAX_PENDING_JOBS = 10000              # 最大待处理 Job 数
    DEFAULT_RETRY_DELAY = 5.0            # 默认重试延迟 (秒)
    MAX_RETRIES = 2                       # 最大重试次数
    DEAD_LETTER_MAX_SIZE = 1000          # 死信队列最大大小


# ===== 验证常量 =====

class VerificationConstants:
    """验证相关常量"""
    LAYER2_SAMPLE_RATE = 0.1             # Layer2 抽样率 10%
    SIMILARITY_THRESHOLD_HIGH = 0.85     # 高相似度阈值
    SIMILARITY_THRESHOLD_LOW = 0.65      # 低相似度阈值
    NODE_LOCK_THRESHOLD = 3              # 节点锁定阈值
    LATENCY_BUFFER_MULTIPLIER = 1.5      # 延迟缓冲倍数
    MILD_LATENCY_PENALTY = 0.7            # 轻微延迟惩罚系数


# ===== 匹配常量 =====

class MatchingConstants:
    """匹配相关常量"""
    NODE_ONLINE_MAX_AGE_SECONDS = 10     # 节点在线最大时间
    DEFAULT_MIN_CONCURRENCY = 1          # 默认最小并发
    DEFAULT_MIN_QUEUE_TOKENS = 1         # 默认最小队列 tokens


# ===== 结算常量 =====

class SettlementConstants:
    """结算相关常量"""
    PLATFORM_FEE_RATE = 0.05             # 平台费率 5%
    NODE_EARN_RATE = 0.95               # 节点获得费率 95%
    ESCROW_BUFFER = 1.1                  # Escrow 缓冲倍数


# ===== 模型限制常量 (MVP) =====

class ModelConstants:
    """模型相关常量"""
    MVP_MODEL = "qwen2.5:7b"             # MVP 限定模型
    MAX_OUTPUT_TOKENS = 256              # 最大输出 tokens
    MAX_LATENCY_MS = 30000               # 最大延迟 (毫秒)
    MIN_LATENCY_MS = 1000                # 最小延迟 (毫秒)


# ===== Stake 分级常量 =====

class StakeConstants:
    """Stake 分级常量"""
    STAKE_PERSONAL = 50.0                # Personal 级 (< 4 GPU)
    STAKE_PROFESSIONAL = 200.0          # Professional 级 (4-7 GPU)
    STAKE_DATACENTER = 1000.0           # Datacenter 级 (>= 8 GPU)


# ===== 价格常量 =====

class PriceConstants:
    """价格相关常量"""
    MIN_BID_PRICE = 0.0                  # 最低出价 (USDC/token)
    DEFAULT_BID_PRICE = 0.000001         # 默认出价 = 1 USDC/1M tokens
    DEFAULT_ASK_PRICE = 0.000001         # 默认要价 = 1 USDC/1M tokens


# ===== Node Status Store 常量 =====

class NodeStatusStoreConstants:
    """Node Status Store 常量"""
    DEFAULT_BACKEND = "memory"           # 默认后端 (memory/redis)
    DEFAULT_TTL_SECONDS = 30             # 默认 TTL


# ===== Stake Tier 枚举 =====

class StakeTier(str, Enum):
    """Stake 等级枚举"""
    PERSONAL = "personal"                # Personal (< 4 GPU)
    PROFESSIONAL = "professional"        # Professional (4-7 GPU)
    DATACENTER = "datacenter"            # Datacenter (>= 8 GPU)


# ===== Node Tier 代码映射 =====

class NodeTierCode:
    """Node Tier 代码映射"""
    PERSONAL = "P"                       # Personal
    PROFESSIONAL = "X"                   # Professional
    DATACENTER = "E"                     # Enterprise/Datacenter


# ===== GPU 数量阈值 =====

class GpuThresholds:
    """GPU 数量阈值"""
    PERSONAL_MAX = 4                     # < 4 GPU
    PROFESSIONAL_MAX = 8                 # 4-7 GPU
    # >= 8 GPU 属于 Datacenter


def get_stake_by_gpu_count(gpu_count: int) -> float:
    """根据 GPU 数量获取对应 Stake 金额"""
    if gpu_count < GpuThresholds.PERSONAL_MAX:
        return StakeConstants.STAKE_PERSONAL
    elif gpu_count < GpuThresholds.PROFESSIONAL_MAX:
        return StakeConstants.STAKE_PROFESSIONAL
    else:
        return StakeConstants.STAKE_DATACENTER


def get_stake_tier_by_gpu_count(gpu_count: int) -> StakeTier:
    """根据 GPU 数量获取对应 Stake 等级"""
    if gpu_count < GpuThresholds.PERSONAL_MAX:
        return StakeTier.PERSONAL
    elif gpu_count < GpuThresholds.PROFESSIONAL_MAX:
        return StakeTier.PROFESSIONAL
    else:
        return StakeTier.DATACENTER
