"""
Job 配置 - DCM v3.2

Job 相关的配置参数，从 config.py 读取默认值
支持环境变量覆盖
"""

import os
from pydantic import BaseModel
from config import settings


class JobConfig(BaseModel):
    """Job 配置 (DCM v3.2)
    
    默认值从 config.py 读取，支持环境变量覆盖
    """
    # 输出 token 上限 (默认 100)
    max_output_tokens: int = 100
    
    # 输入 token 上限
    max_input_tokens: int = 128000
    
    # 最大延迟 (ms)
    max_latency_ms: int = 30000
    
    # 最小延迟 (ms)
    min_latency_ms: int = 1000
    
    # 默认输出 token (当未指定时)
    default_output_tokens: int = 1024
    
    # 最大 bid price
    max_bid_price: float = 10.0
    
    # 最小 bid price
    min_bid_price: float = 0.001
    
    # 最大重试次数
    max_retries: int = 2


def load_job_config() -> JobConfig:
    """从 config.py 和环境变量加载配置"""
    config = JobConfig(
        # 从 config.py 读取默认值
        max_output_tokens=settings.max_output_tokens,
        max_latency_ms=settings.max_latency_ms,
        min_latency_ms=settings.min_latency_ms,
        min_bid_price=settings.min_bid_price,
        max_retries=settings.max_retry_count,
    )
    
    # 从环境变量覆盖
    if os.environ.get("DCM_MAX_OUTPUT_TOKENS"):
        config.max_output_tokens = int(os.environ["DCM_MAX_OUTPUT_TOKENS"])
    
    if os.environ.get("DCM_MAX_INPUT_TOKENS"):
        config.max_input_tokens = int(os.environ["DCM_MAX_INPUT_TOKENS"])
    
    if os.environ.get("DCM_MAX_LATENCY_MS"):
        config.max_latency_ms = int(os.environ["DCM_MAX_LATENCY_MS"])
    
    if os.environ.get("DCM_MIN_LATENCY_MS"):
        config.min_latency_ms = int(os.environ["DCM_MIN_LATENCY_MS"])
    
    if os.environ.get("DCM_DEFAULT_OUTPUT_TOKENS"):
        config.default_output_tokens = int(os.environ["DCM_DEFAULT_OUTPUT_TOKENS"])
    
    if os.environ.get("DCM_MAX_BID_PRICE"):
        config.max_bid_price = float(os.environ["DCM_MAX_BID_PRICE"])
    
    if os.environ.get("DCM_MIN_BID_PRICE"):
        config.min_bid_price = float(os.environ["DCM_MIN_BID_PRICE"])
    
    if os.environ.get("DCM_MAX_RETRIES"):
        config.max_retries = int(os.environ["DCM_MAX_RETRIES"])
    
    return config


# 全局配置实例（懒加载）
_job_config: JobConfig = None


def get_job_config() -> JobConfig:
    """获取 Job 配置（懒加载）"""
    global _job_config
    if _job_config is None:
        _job_config = load_job_config()
    return _job_config


def reload_job_config() -> JobConfig:
    """重新加载配置"""
    global _job_config
    _job_config = load_job_config()
    return _job_config
