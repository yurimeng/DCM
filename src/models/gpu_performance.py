"""
GPU Performance Dictionary - DCM v3.2

定义不同 GPU/配置的最大吞吐量 (tokens/second)
用于计算 Node 的 max_queue

配置参数:
- QUEUE_WINDOW_SECONDS: 时间窗口 (秒), 默认 30
- max_queue = throughput * QUEUE_WINDOW_SECONDS
"""

# 时间窗口配置 (秒)
QUEUE_WINDOW_SECONDS = 30

# GPU 性能词典 (tokens/second)
GPU_PERFORMANCE_DICT = {
    # Apple Silicon
    "apple_m5_pro": {
        24: {"ollama": 120, "vllm": 180, "lmstudio": 100},
        48: {"ollama": 240, "vllm": 360, "lmstudio": 200},
    },
    "apple_m4_max": {
        64: {"ollama": 200, "vllm": 300, "lmstudio": 160},
        128: {"ollama": 400, "vllm": 600, "lmstudio": 320},
    },
    "apple_m3_ultra": {
        128: {"ollama": 180, "vllm": 270, "lmstudio": 140},
    },
    "apple_m2_ultra": {
        64: {"ollama": 150, "vllm": 220, "lmstudio": 120},
        128: {"ollama": 300, "vllm": 440, "lmstudio": 240},
    },
    "apple_m2_max": {
        32: {"ollama": 100, "vllm": 150, "lmstudio": 80},
        64: {"ollama": 200, "vllm": 300, "lmstudio": 160},
    },
    
    # NVIDIA RTX Series
    "rtx_4090": {
        24: {"ollama": 80, "vllm": 150, "tensorrt": 200, "lmstudio": 100},
    },
    "rtx_3090": {
        24: {"ollama": 60, "vllm": 100, "tensorrt": 140, "lmstudio": 70},
    },
    "rtx_4080_super": {
        16: {"ollama": 70, "vllm": 120, "tensorrt": 160, "lmstudio": 80},
    },
    "rtx_4080": {
        16: {"ollama": 60, "vllm": 100, "tensorrt": 140, "lmstudio": 70},
    },
    "rtx_4070_ti_super": {
        16: {"ollama": 50, "vllm": 90, "tensorrt": 120, "lmstudio": 60},
    },
    "rtx_4070": {
        12: {"ollama": 40, "vllm": 70, "tensorrt": 100, "lmstudio": 50},
    },
    
    # NVIDIA A Series
    "a100": {
        40: {"ollama": 100, "vllm": 200, "tensorrt": 300, "lmstudio": 120},
        80: {"ollama": 200, "vllm": 400, "tensorrt": 600, "lmstudio": 240},
    },
    "a6000": {
        48: {"ollama": 120, "vllm": 220, "tensorrt": 320, "lmstudio": 140},
    },
    "a5000": {
        24: {"ollama": 80, "vllm": 150, "tensorrt": 200, "lmstudio": 100},
    },
    "a4000": {
        16: {"ollama": 50, "vllm": 90, "tensorrt": 120, "lmstudio": 60},
    },
    
    # NVIDIA H Series
    "h100": {
        80: {"ollama": 180, "vllm": 400, "tensorrt": 600, "lmstudio": 200},
        160: {"ollama": 360, "vllm": 800, "tensorrt": 1200, "lmstudio": 400},
    },
    "h200": {
        80: {"ollama": 200, "vllm": 450, "tensorrt": 680, "lmstudio": 220},
        144: {"ollama": 360, "vllm": 800, "tensorrt": 1200, "lmstudio": 400},
    },
    "h20": {
        80: {"ollama": 120, "vllm": 250, "tensorrt": 350, "lmstudio": 140},
    },
    
    # NVIDIA L Series (Inference Optimized)
    "l40s": {
        48: {"ollama": 100, "vllm": 200, "tensorrt": 280, "lmstudio": 120},
    },
    "l40": {
        48: {"ollama": 80, "vllm": 160, "tensorrt": 220, "lmstudio": 100},
    },
    "l4": {
        24: {"ollama": 60, "vllm": 100, "tensorrt": 140, "lmstudio": 70},
    },
    
    # NVIDIA Other
    "v100": {
        16: {"ollama": 50, "vllm": 80, "tensorrt": 120, "lmstudio": 60},
        32: {"ollama": 100, "vllm": 160, "tensorrt": 240, "lmstudio": 120},
    },
    
    # AMD
    "mi300x": {
        192: {"ollama": 150, "vllm": 300, "tensorrt": 400, "lmstudio": 180},
    },
    "mi250": {
        128: {"ollama": 100, "vllm": 200, "tensorrt": 280, "lmstudio": 120},
    },
    "radeon_rx_7900_xtx": {
        24: {"ollama": 40, "vllm": 70, "lmstudio": 50},
    },
    "radeon_rx_7900_xt": {
        20: {"ollama": 35, "vllm": 60, "lmstudio": 45},
    },
    
    # Intel
    "gaudi2": {
        96: {"ollama": 80, "vllm": 150, "tensorrt": 200, "lmstudio": 100},
    },
    "max_1550": {
        128: {"ollama": 100, "vllm": 180, "tensorrt": 250, "lmstudio": 120},
    },
}


def get_gpu_performance(gpu_type: str, memory_gb: int, runtime: str) -> int:
    """
    根据 GPU 类型、内存和 runtime 获取最大吞吐量 (tokens/second)
    
    Args:
        gpu_type: GPU 类型 (如 "apple_m5_pro", "rtx_4090")
        memory_gb: 内存大小 (GB)
        runtime: 运行时 (如 "ollama", "vllm")
        
    Returns:
        最大吞吐量 (tokens/second)
    """
    gpu_type_lower = (gpu_type or "unknown").lower().replace(" ", "_").replace("-", "_")
    runtime_lower = (runtime or "ollama").lower()
    
    # 查找 GPU 类型
    if gpu_type_lower not in GPU_PERFORMANCE_DICT:
        # 尝试模糊匹配
        for known_type in GPU_PERFORMANCE_DICT:
            if gpu_type_lower in known_type or known_type in gpu_type_lower:
                gpu_type_lower = known_type
                break
        else:
            # 默认值
            return 50
    
    memory_config = GPU_PERFORMANCE_DICT[gpu_type_lower]
    
    # 查找内存配置 (精确匹配优先，然后模糊匹配)
    tokens_per_second = None
    
    if memory_gb in memory_config:
        runtime_config = memory_config[memory_gb]
        if runtime_lower in runtime_config:
            tokens_per_second = runtime_config[runtime_lower]
    
    # 如果没找到，尝试查找同一 GPU 类型的其他内存配置
    if tokens_per_second is None:
        for mem, runtime_config in memory_config.items():
            if runtime_lower in runtime_config:
                tokens_per_second = runtime_config[runtime_lower]
                break
    
    # 如果还没找到，返回默认值
    if tokens_per_second is None:
        # 根据内存大小估算
        tokens_per_second = min(500, max(20, memory_gb * 2))
    
    return tokens_per_second


def calculate_max_queue(gpu_type: str, memory_gb: int, runtime: str, gpu_count: int = 1) -> int:
    """
    计算 Node 的 max_queue
    
    max_queue = 单卡吞吐量 * GPU 数量 * 时间窗口
    
    Args:
        gpu_type: GPU 类型
        memory_gb: 内存大小 (GB)
        runtime: 运行时
        gpu_count: GPU 数量
        
    Returns:
        max_queue = 可处理的总 token 数 (input + output)
    """
    per_gpu_throughput = get_gpu_performance(gpu_type, memory_gb, runtime)
    return per_gpu_throughput * gpu_count * QUEUE_WINDOW_SECONDS


# 便捷函数
def get_default_max_queue() -> int:
    """获取默认的 max_queue (当无法确定时)"""
    return 50
