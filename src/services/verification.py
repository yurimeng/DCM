"""
Verification Service - F5: 验证服务
来源: PRD 0.2 Section 5.2 & Function/F5
"""

import hashlib
import random
from typing import Optional, Tuple
from datetime import datetime
from ..models import Match, Job, Node
from config import settings


class VerificationService:
    """验证服务"""
    
    def __init__(self):
        # Layer 2 双跑结果存储
        self._layer2_jobs: dict[str, dict] = {}
        # 节点异常计数
        self._node_violations: dict[str, int] = {}
    
    def verify_layer1(self, match: Match, job: Job,
                      result: str, result_hash: str,
                      actual_latency_ms: int,
                      actual_output_tokens: int) -> Tuple[bool, str]:
        """
        Layer 1 基础验证（每次执行）
        
        验证项:
        1. 输出哈希: SHA256(result) == submitted_hash
        2. Token 上限: actual_output_tokens <= job.output_tokens_limit
        3. 延迟窗口: actual_latency <= job.max_latency × 1.5
        
        返回: (是否通过, 失败原因)
        """
        # 1. 哈希验证
        computed_hash = hashlib.sha256(result.encode()).hexdigest()
        if computed_hash != result_hash:
            return False, f"hash_mismatch: expected {result_hash}, got {computed_hash}"
        
        # 2. Token 上限验证
        if actual_output_tokens > job.output_tokens_limit:
            return False, f"token_limit_exceeded: limit {job.output_tokens_limit}, got {actual_output_tokens}"
        
        # 3. 延迟窗口验证
        max_allowed_latency = job.max_latency * settings.latency_buffer_multiplier
        if actual_latency_ms > max_allowed_latency:
            return False, f"latency_exceeded: max {max_allowed_latency}ms, got {actual_latency_ms}ms"
        
        return True, ""
    
    def check_latency_penalty(self, job: Job, actual_latency_ms: int) -> Tuple[bool, bool]:
        """
        检查延迟是否触发降价结算
        
        返回: (是否失败, 是否轻微超标)
        - False, False: 通过
        - True, False: 严重超标，失败
        - True, True: 轻微超标，降价结算
        """
        if actual_latency_ms <= job.max_latency:
            return False, False  # 正常
        
        max_allowed = job.max_latency * settings.latency_buffer_multiplier
        if actual_latency_ms > max_allowed:
            return True, False  # 严重超标，失败
        
        return True, True  # 轻微超标，降价结算
    
    def should_trigger_layer2(self) -> bool:
        """
        判定是否触发 Layer 2 抽样双跑
        10% 概率触发
        """
        return random.random() < settings.layer2_sample_rate
    
    def trigger_layer2(self, match_id: str, job: Job, 
                       original_result: str) -> str:
        """
        触发 Layer 2 双跑
        
        返回: 新的 Job ID（用于第二节点执行）
        """
        layer2_job_id = f"layer2_{match_id}_{len(self._layer2_jobs)}"
        self._layer2_jobs[layer2_job_id] = {
            "original_match_id": match_id,
            "original_result": original_result,
            "created_at": datetime.utcnow(),
            "completed": False,
            "second_result": None,
        }
        return layer2_job_id
    
    def submit_layer2_result(self, layer2_job_id: str, second_result: str) -> Tuple[float, str]:
        """
        提交 Layer 2 第二节点结果
        
        返回: (相似度, 判定结果)
        """
        if layer2_job_id not in self._layer2_jobs:
            raise ValueError(f"Layer2 job not found: {layer2_job_id}")
        
        layer2_data = self._layer2_jobs[layer2_job_id]
        layer2_data["second_result"] = second_result
        layer2_data["completed"] = True
        
        # 计算相似度（简化版，实际应使用 ROUGE-L）
        similarity = self._calculate_similarity(
            layer2_data["original_result"],
            second_result
        )
        
        # 判定
        if similarity > settings.similarity_threshold_high:
            verdict = "consistent"  # 一致，通过
        elif similarity > settings.similarity_threshold_low:
            verdict = "recorded"  # 记录，不处罚
        else:
            verdict = "inconsistent"  # 不一致，触发复核
        
        return similarity, verdict
    
    def record_violation(self, node_id: str) -> Tuple[bool, int]:
        """
        记录节点违规
        
        返回: (是否应锁定节点, 当前违规次数)
        连续 3 次不一致 → 锁定
        """
        count = self._node_violations.get(node_id, 0) + 1
        self._node_violations[node_id] = count
        
        should_lock = count >= settings.node_lock_threshold
        return should_lock, count
    
    def get_node_violations(self, node_id: str) -> int:
        """获取节点违规次数"""
        return self._node_violations.get(node_id, 0)
    
    def reset_violations(self, node_id: str) -> None:
        """重置节点违规计数（正常完成后调用）"""
        self._node_violations.pop(node_id, None)
    
    @staticmethod
    def _calculate_similarity(text1: str, text2: str) -> float:
        """
        计算文本相似度
        
        简化版：使用字符级 Jaccard 相似度
        实际应使用 ROUGE-L 或 edit distance
        """
        if not text1 or not text2:
            return 0.0
        
        set1 = set(text1.split())
        set2 = set(text2.split())
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0


# 单例
verification_service = VerificationService()
