"""
Retry Service - F4: 失败重试机制
来源: PRD 0.2 Section 5.4 & Function/F4
"""

from typing import Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
from ..models import Job, JobStatus, Node, Match
from .matching import matching_service
from .escrow import escrow_service
from config import settings


class FailureType(str, Enum):
    """失败类型"""
    NODE_OFFLINE = "node_offline"           # 节点掉线
    NODE_ERROR = "node_error"               # 节点返回错误
    LATENCY_EXCEEDED = "latency_exceeded"   # 延迟超标
    VERIFICATION_FAILED = "verification_failed"  # 验证失败


class RetryService:
    """失败重试服务"""
    
    def __init__(self):
        # 重试队列
        self._retry_queue: list[dict] = []
        # 失败记录
        self._failure_log: list[dict] = []
    
    def handle_failure(self, match: Match, job: Job,
                       failure_type: FailureType,
                       reason: str = "") -> Optional[Job]:
        """
        处理失败
        
        返回: 如果可以重试，返回新的 Job；否则返回 None
        """
        # 记录失败
        self._log_failure(match, job, failure_type, reason)
        
        # 检查重试次数
        if job.retry_count >= settings.max_retry_count:
            # 重试次数用完，标记失败
            return self._final_failure(job, failure_type, reason)
        
        # 执行重试
        return self._retry(job, match)
    
    def handle_node_offline(self, node_id: str, match: Match) -> Optional[Job]:
        """
        处理节点掉线
        30s 内无响应视为掉线
        """
        # 检查是否超时
        time_diff = datetime.utcnow() - match.matched_at
        if time_diff.total_seconds() < settings.heartbeat_timeout_seconds:
            # 还在等待期，不处理
            return None
        
        job = self._get_job_from_match(match)
        if not job:
            return None
        
        return self.handle_failure(match, job, FailureType.NODE_OFFLINE)
    
    def handle_node_error(self, match: Match, job: Job,
                         error_type: str) -> Optional[Job]:
        """
        处理节点返回错误（空结果/格式错误/token超限）
        """
        reason = f"node_error: {error_type}"
        return self.handle_failure(match, job, FailureType.NODE_ERROR, reason)
    
    def handle_latency_exceeded(self, match: Match, job: Job,
                               actual_latency: int) -> Optional[Job]:
        """
        处理延迟超标
        """
        reason = f"latency_exceeded: {actual_latency}ms > {job.max_latency * settings.latency_buffer_multiplier}ms"
        return self.handle_failure(match, job, FailureType.LATENCY_EXCEEDED, reason)
    
    def handle_verification_failed(self, match: Match, job: Job,
                                   reason: str) -> Optional[Job]:
        """
        处理验证失败
        """
        return self.handle_failure(match, job, FailureType.VERIFICATION_FAILED, reason)
    
    def _retry(self, job: Job, old_match: Match) -> Optional[Job]:
        """
        执行重试
        
        规则:
        - 最多重试 2 次
        - 排除当前失败节点
        - 选择下一个最低 ask_price 的 online 节点
        """
        # 创建新 Job（复用原 job_id，增加 retry_count）
        new_job = Job(
            model=job.model,
            input_tokens=job.input_tokens,
            output_tokens_limit=job.output_tokens_limit,
            max_latency=job.max_latency,
            bid_price=job.bid_price,
            callback_url=job.callback_url,
        )
        new_job.job_id = job.job_id  # 复用 job_id
        new_job.retry_count = job.retry_count + 1
        new_job.status = JobStatus.PENDING
        
        # 加入撮合队列
        matching_service.add_job(new_job)
        
        # 尝试立即撮合（排除原节点）
        self._match_with_exclusion(new_job, old_match.node_id)
        
        return new_job
    
    def _match_with_exclusion(self, job: Job, exclude_node_id: str) -> None:
        """
        排除指定节点后撮合
        """
        # 临时移除排除的节点
        excluded_node = matching_service._online_nodes.pop(exclude_node_id, None)
        
        try:
            # 触发撮合
            new_match = matching_service.trigger_match(job.job_id)
            if new_match:
                # 标记为重试
                new_match.retry_count = job.retry_count
                new_match.original_match_id = job.job_id
        finally:
            # 恢复节点
            if excluded_node:
                matching_service._online_nodes[exclude_node_id] = excluded_node
    
    def _final_failure(self, job: Job, failure_type: FailureType,
                       reason: str) -> None:
        """
        最终失败处理
        - Job 状态设为 failed
        - Escrow 全额退款
        """
        job.status = JobStatus.FAILED
        job.completed_at = datetime.utcnow()
        
        # 触发 Escrow 全额退款
        escrow_service.refund(job.job_id, f"final_failure: {failure_type.value}")
    
    def _log_failure(self, match: Match, job: Job,
                    failure_type: FailureType, reason: str) -> None:
        """记录失败日志"""
        self._failure_log.append({
            "match_id": match.match_id,
            "job_id": job.job_id,
            "node_id": match.node_id,
            "failure_type": failure_type.value,
            "reason": reason,
            "retry_count": job.retry_count,
            "timestamp": datetime.utcnow(),
        })
    
    def _get_job_from_match(self, match: Match) -> Optional[Job]:
        """从 Match 获取关联的 Job（简化版）"""
        # 实际应从数据库/存储获取
        return None  # 需要 JobService 配合
    
    def get_failure_stats(self) -> dict:
        """获取失败统计"""
        stats = {
            "total_failures": len(self._failure_log),
            "by_type": {},
            "by_node": {},
        }
        
        for log in self._failure_log:
            ft = log["failure_type"]
            stats["by_type"][ft] = stats["by_type"].get(ft, 0) + 1
            
            node_id = log["node_id"]
            stats["by_node"][node_id] = stats["by_node"].get(node_id, 0) + 1
        
        return stats


# 单例
retry_service = RetryService()
