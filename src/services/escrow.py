"""
Escrow Service - F6: 结算服务
来源: PRD 0.2 Section 5.5 & Function/F6

支持功能:
- Escrow 锁定
- Job 完成后延迟自动结算
- 取消功能
"""

from typing import Optional, List
from datetime import datetime, timedelta
from ..models import Escrow, EscrowStatus, SettlementRequest
from config import settings
from .settlement_config import settlement_config
import threading
import logging

logger = logging.getLogger(__name__)


class EscrowService:
    """
    Escrow 管理服务
    
    功能:
    - 创建 Escrow 并锁定资金
    - Job 完成后进入 COMPLETED 状态，延迟 auto_complete_seconds 后自动结算
    - 支持取消（在 COMPLETED 之前）
    """
    
    def __init__(self):
        # 内存存储（MVP），后续替换为数据库
        self._escrows: dict[str, Escrow] = {}
        self._auto_complete_timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()  # 线程安全
    
    def create_escrow(self, job_id: str, bid_price: float, 
                      input_tokens: int, output_tokens_limit: int,
                      match_id: Optional[str] = None) -> Escrow:
        """
        创建 Escrow 并锁定资金
        
        公式: escrow_amount = bid_price × (input_tokens + output_tokens_limit) / 1M × 1.1
        """
        locked_amount = self._calculate_escrow(
            bid_price, input_tokens, output_tokens_limit
        )
        
        escrow = Escrow(
            job_id=job_id,
            match_id=match_id,
            locked_amount=locked_amount,
            status=EscrowStatus.LOCKED,
        )
        
        with self._lock:
            self._escrows[job_id] = escrow
        
        logger.info(f"Escrow created: job_id={job_id}, locked_amount={locked_amount}")
        return escrow
    
    def get_escrow(self, job_id: str) -> Optional[Escrow]:
        """获取 Escrow"""
        return self._escrows.get(job_id)
    
    def get_all_escrows(self) -> List[Escrow]:
        """获取所有 Escrow"""
        return list(self._escrows.values())
    
    def complete_job(self, job_id: str) -> Escrow:
        """
        Job 执行完成，标记为待结算
        
        状态流转: LOCKED → COMPLETED → (延迟) → SETTLED
        """
        escrow = self._escrows.get(job_id)
        if not escrow:
            raise ValueError(f"Escrow not found for job_id: {job_id}")
        
        if escrow.status != EscrowStatus.LOCKED:
            raise ValueError(f"Cannot complete job: escrow status is {escrow.status}")
        
        # 计算自动完成时间
        auto_complete_seconds = settlement_config.escrow_auto_complete_seconds
        auto_complete_at = datetime.utcnow() + timedelta(seconds=auto_complete_seconds)
        
        # 更新状态
        escrow.status = EscrowStatus.COMPLETED
        escrow.completed_at = datetime.utcnow()
        escrow.auto_complete_at = auto_complete_at
        
        # 启动延迟自动完成定时器
        self._schedule_auto_complete(job_id, auto_complete_seconds)
        
        logger.info(
            f"Escrow completed: job_id={job_id}, "
            f"auto_complete_at={auto_complete_at.isoformat()}"
        )
        return escrow
    
    def _schedule_auto_complete(self, job_id: str, delay_seconds: int):
        """安排自动完成"""
        with self._lock:
            # 取消已有的定时器
            if job_id in self._auto_complete_timers:
                self._auto_complete_timers[job_id].cancel()
            
            # 创建新的定时器
            timer = threading.Timer(delay_seconds, self._auto_complete, args=[job_id])
            self._auto_complete_timers[job_id] = timer
            timer.start()
            
            logger.debug(f"Auto-complete scheduled: job_id={job_id}, delay={delay_seconds}s")
    
    def _auto_complete(self, job_id: str):
        """自动完成结算（内部调用）"""
        with self._lock:
            escrow = self._escrows.get(job_id)
            if not escrow:
                logger.warning(f"Escrow not found for auto-complete: {job_id}")
                return
            
            if escrow.status != EscrowStatus.COMPLETED:
                logger.warning(
                    f"Escrow status changed during delay: {job_id}, "
                    f"status={escrow.status}"
                )
                return
            
            # 执行自动结算
            try:
                self._execute_settlement_internal(escrow)
                logger.info(f"Escrow auto-completed: job_id={job_id}")
            except Exception as e:
                logger.error(f"Escrow auto-complete failed: {job_id}, error={e}")
            finally:
                # 清理定时器
                if job_id in self._auto_complete_timers:
                    del self._auto_complete_timers[job_id]
    
    def execute_settlement(self, request: SettlementRequest) -> Escrow:
        """
        执行结算（内部方法，由外部触发）
        
        分配:
        - Node: 95%
        - System: 5%
        - 余额: 退还 Buyer
        """
        escrow = None
        with self._lock:
            for e in self._escrows.values():
                if e.job_id == request.match_id or e.match_id == request.match_id:
                    escrow = e
                    break
        
        if not escrow:
            raise ValueError(f"Escrow not found for match_id: {request.match_id}")
        
        # 取消自动完成定时器
        self._cancel_auto_complete_timer(escrow.job_id)
        
        return self._execute_settlement_internal(escrow, request)
    
    def _execute_settlement_internal(
        self, 
        escrow: Escrow,
        request: Optional[SettlementRequest] = None
    ) -> Escrow:
        """内部结算方法"""
        # 计算实际费用（使用预估价格）
        if request:
            actual_tokens = request.actual_tokens
            locked_price = request.locked_price
            
            actual_cost = self._calculate_cost(locked_price, actual_tokens)
            
            # 轻微延迟超标：降价结算
            if request.is_mild_latency_penalty:
                actual_cost *= settings.mild_latency_penalty  # 0.7
        else:
            # 自动完成：使用锁定的金额
            actual_tokens = 0
            actual_cost = escrow.locked_amount
        
        # 结算分配
        platform_fee = actual_cost * settlement_config.platform_fee_rate
        node_earn = actual_cost * settlement_config.node_earn_rate
        refund_amount = escrow.locked_amount - actual_cost
        
        # 更新 Escrow
        escrow.spent_amount = actual_cost
        escrow.refund_amount = max(0, refund_amount)
        if request:
            escrow.actual_tokens = actual_tokens
        escrow.actual_cost = actual_cost
        escrow.platform_fee = platform_fee
        escrow.node_earn = node_earn
        escrow.status = EscrowStatus.SETTLED
        escrow.settled_at = datetime.utcnow()
        
        return escrow
    
    def manual_settle(self, job_id: str) -> Escrow:
        """
        手动完成结算（跳过延迟）
        """
        escrow = self._escrows.get(job_id)
        if not escrow:
            raise ValueError(f"Escrow not found for job_id: {job_id}")
        
        if escrow.status not in [EscrowStatus.COMPLETED, EscrowStatus.LOCKED]:
            raise ValueError(f"Cannot settle: escrow status is {escrow.status}")
        
        # 取消自动完成定时器
        self._cancel_auto_complete_timer(job_id)
        
        return self._execute_settlement_internal(escrow)
    
    def cancel(self, job_id: str, reason: str, cancelled_by: str = "system") -> Escrow:
        """
        取消 Escrow（全额退款）
        
        只能在 COMPLETED 之前取消（LOCKED 状态）
        """
        if not settlement_config.escrow_allow_cancellation:
            raise ValueError("Escrow cancellation is not allowed")
        
        escrow = self._escrows.get(job_id)
        if not escrow:
            raise ValueError(f"Escrow not found for job_id: {job_id}")
        
        # 只能在 LOCKED 或 COMPLETED 状态取消
        if escrow.status not in [EscrowStatus.LOCKED, EscrowStatus.COMPLETED]:
            raise ValueError(
                f"Cannot cancel: escrow status is {escrow.status}, "
                f"only LOCKED or COMPLETED allowed"
            )
        
        # 取消自动完成定时器
        self._cancel_auto_complete_timer(job_id)
        
        # 全额退款
        escrow.refund_amount = escrow.locked_amount
        escrow.status = EscrowStatus.CANCELLED
        escrow.refunded_at = datetime.utcnow()
        escrow.cancelled_at = datetime.utcnow()
        escrow.cancelled_by = cancelled_by
        escrow.cancel_reason = reason
        
        logger.info(
            f"Escrow cancelled: job_id={job_id}, "
            f"cancelled_by={cancelled_by}, reason={reason}"
        )
        return escrow
    
    def refund(self, job_id: str, reason: str) -> Escrow:
        """
        全额退款（手动触发）
        """
        escrow = self._escrows.get(job_id)
        if not escrow:
            raise ValueError(f"Escrow not found for job_id: {job_id}")
        
        # 取消自动完成定时器
        self._cancel_auto_complete_timer(job_id)
        
        escrow.refund_amount = escrow.locked_amount
        escrow.status = EscrowStatus.REFUNDED
        escrow.refunded_at = datetime.utcnow()
        escrow.refund_reason = reason
        
        return escrow
    
    def _cancel_auto_complete_timer(self, job_id: str):
        """取消自动完成定时器"""
        with self._lock:
            if job_id in self._auto_complete_timers:
                self._auto_complete_timers[job_id].cancel()
                del self._auto_complete_timers[job_id]
                logger.debug(f"Auto-complete timer cancelled: job_id={job_id}")
    
    def get_pending_auto_complete(self) -> List[Escrow]:
        """获取待自动完成的 Escrow 列表"""
        return [
            e for e in self._escrows.values()
            if e.status == EscrowStatus.COMPLETED
        ]
    
    @staticmethod
    def _calculate_escrow(bid_price: float, input_tokens: int, 
                          output_tokens_limit: int) -> float:
        """计算 Escrow 锁定金额"""
        total_tokens = input_tokens + output_tokens_limit
        base_cost = bid_price * total_tokens / 1_000_000
        return round(base_cost * settings.escrow_buffer, 8)
    
    @staticmethod
    def _calculate_cost(locked_price: float, actual_tokens: int) -> float:
        """计算实际费用"""
        return round(locked_price * actual_tokens / 1_000_000, 8)


# 单例
escrow_service = EscrowService()
