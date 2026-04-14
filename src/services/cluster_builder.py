"""
Cluster Builder - DCM v3.2
根据 region -> stake_tier -> loaded moels -> reliability 动态组建 Cluster
"""

import hashlib
from typing import Optional, List
from src.models.node import Node, Reliability


# ===== ID 编码表 =====

REGION_CODES = {
    "us-west": "usw",
    "us-east": "use",
    "us-central": "usc",
    "eu-west": "euw",
    "eu-central": "euc",
    "eu-east": "eue",
    "asia-east": "ase",
    "asia-south": "ass",
    "asia-central": "asc",
    "cn": "cn",
    "CN": "cn",
    "china": "cn",
    "unknown": "unk",
}

TIER_CODES = {
    "personal": "P",
    "professional": "X",
    "enterprise": "E",
}

MODEL_FAMILY_CODES = {
    "qwen": "Q",
    "llama": "L",
    "gemma": "G",
    "mistral": "M",
    "unknown": "X",
}

RELIABILITY_CODES = {
    "A": "A",
    "B": "B",
    "C": "C",
}


def get_model_family(models: List[str]) -> str:
    """从模型列表获取主模型家族
    
    策略:
    1. 如果有 qwen 系列，返回 qwen
    2. 如果有 llama 系列，返回 llama
    3. 否则返回第一个模型的名字或 "unknown"
    """
    if not models:
        return "unknown"
    
    for model in models:
        if "qwen" in model.lower():
            return "qwen"
        if "llama" in model.lower():
            return "llama"
        if "gemma" in model.lower():
            return "gemma"
        if "mistral" in model.lower():
            return "mistral"
    
    # 返回第一个模型的主名（去掉版本号）
    return models[0].split(":")[0]


def build_cluster_id(
    region: str,
    stake_tier: str,
    models: List[str],
    quality_score: float = 0.9,
    success_rate: float = 0.95,
) -> str:
    """
    根据 Node 属性动态生成 Cluster ID
    
    格式: C_{region_code}{tier_code}_{model_code}{rel_code}_{hash}
    
    例如:
    - C_usw_P_Q_A_3f2e
    - C_euc_X_L_B_8e14
    
    Args:
        region: 区域
        stake_tier: 质押等级
        models: 加载的模型列表
        quality_score: 质量评分 (默认 0.9)
        success_rate: 成功率 (默认 0.95)
        
    Returns:
        Cluster ID (简洁格式)
    """
    # 编码 region
    region_key = region.lower().replace(" ", "-").replace("_", "-")
    region_code = REGION_CODES.get(region_key, "unk")[:3]
    
    # 编码 stake_tier
    tier_code = TIER_CODES.get(stake_tier.lower(), "P")
    
    # 编码模型家族
    model_family = get_model_family(models)
    model_code = MODEL_FAMILY_CODES.get(model_family.lower(), "X")
    
    # 编码可靠性等级
    rel_tier = _get_reliability_tier(quality_score, success_rate)
    
    # 生成短 hash (取前4位)
    hash_input = f"{region}:{stake_tier}:{models}:{quality_score}:{success_rate}"
    hash_suffix = hashlib.md5(hash_input.encode()).hexdigest()[:4]
    
    return f"C_{region_code}{tier_code}_{model_code}{rel_tier}_{hash_suffix}"


def _get_reliability_tier(quality_score: float, success_rate: float) -> str:
    """根据 quality_score 和 success_rate 计算可靠性等级
    
    等级划分:
    - A: quality_score >= 0.95 && success_rate >= 0.98
    - B: quality_score >= 0.9 && success_rate >= 0.95
    - C: 其他
    """
    if quality_score >= 0.95 and success_rate >= 0.98:
        return "A"
    elif quality_score >= 0.9 and success_rate >= 0.95:
        return "B"
    else:
        return "C"


def get_reliability_tier(reliability: Reliability) -> str:
    """根据 reliability 对象计算可靠性等级 (兼容旧接口)"""
    return _get_reliability_tier(reliability.quality_score, reliability.success_rate)


def build_cluster_id_from_node(node: Node) -> str:
    """
    根据 Node 动态生成 Cluster ID
    
    Args:
        node: Node 实例
        
    Returns:
        Cluster ID
    """
    return build_cluster_id(
        region=node.location.region,
        stake_tier=node.economy.stake_tier,
        models=node.runtime.loaded_models,
        quality_score=node.reliability.quality_score,
        success_rate=node.reliability.success_rate
    )


def should_update_cluster(node: Node, new_cluster_id: str) -> bool:
    """
    检查是否需要更新 Cluster ID
    
    当以下条件变化时需要更新:
    1. region 变化
    2. stake_tier 变化
    3. loaded_models 变化 (主模型家族)
    4. reliability 等级变化
    """
    current_cluster_id = node.network.cluster_id
    
    if current_cluster_id is None:
        return True
    
    if current_cluster_id != new_cluster_id:
        return True
    
    return False


def update_node_cluster(node: Node) -> Optional[str]:
    """
    更新 Node 的 Cluster ID
    
    根据当前 Node 属性重新计算 Cluster ID
    如果发生变化则更新并返回新的 cluster_id
    
    Args:
        node: Node 实例
        
    Returns:
        新的 cluster_id 或 None（如果没变化）
    """
    new_cluster_id = build_cluster_id_from_node(node)
    
    if should_update_cluster(node, new_cluster_id):
        node.network.cluster_id = new_cluster_id
        return new_cluster_id
    
    return None


# ===== 测试 =====

if __name__ == "__main__":
    from src.models.node import Node, NodeState, Reliability, Economy, Runtime, Location, Hardware, Capability, Pricing, Network
    
    # 示例 Node
    node = Node(
        node_id="node_001",
        user_id="user_xxx",
        location=Location(region="us-west", hostname="node-001"),
        hardware=Hardware(gpu_type="RTX4090", gpu_count=2, vram_per_gpu_gb=24),
        runtime=Runtime(type="ollama", loaded_models=["qwen3-8b", "llama3-8b"]),
        capability=Capability(max_concurrency_total=4, tokens_per_sec=1200, max_queue_tokens=3000),
        pricing=Pricing(ask_price_usdc_per_mtoken=0.5),
        reliability=Reliability(avg_latency_ms=100, success_rate=0.98, quality_score=0.95),
        economy=Economy(stake_amount=50.0, stake_required=50.0, stake_tier="personal"),
        state=NodeState(status="online", active_jobs=0, available_concurrency=4, available_queue_tokens=3000),
        network=Network(cluster_id=None),
    )
    
    # 生成 Cluster ID
    cluster_id = build_cluster_id_from_node(node)
    print(f"Generated Cluster ID: {cluster_id}")
    
    # 更新 Node
    new_id = update_node_cluster(node)
    print(f"Updated Cluster ID: {new_id}")
    print(f"Node network.cluster_id: {node.network.cluster_id}")
    
    # 测试不同参数
    print("\n--- Different Parameters ---")
    
    # 测试不同 region
    node2 = Node(
        node_id="node_002",
        user_id="user_xxx",
        location=Location(region="eu-central", hostname="node-002"),
        hardware=Hardware(gpu_type="A100", gpu_count=4, vram_per_gpu_gb=80),
        runtime=Runtime(type="vllm", loaded_models=["llama3-70b"]),
        reliability=Reliability(avg_latency_ms=80, success_rate=0.99, quality_score=0.97),
        economy=Economy(stake_tier="professional"),
        state=NodeState(status="online", active_jobs=0, available_concurrency=4, available_queue_tokens=6000),
        network=Network(),
    )
    
    cluster_id2 = build_cluster_id_from_node(node2)
    print(f"Node2 Cluster ID (eu-central, professional, llama): {cluster_id2}")
