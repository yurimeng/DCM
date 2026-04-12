"""
Escrow Service - F6: 结算服务
来源: PRD 0.2 Section 5.5 & Function/F6
"""

from typing import Optional
from datetime import datetime
from ..models import Escrow, EscrowStatus, SettlementRequest
from config import settings


class EscrowService:
    """Escrow 管理服务"""
    
    def __init__(self):
        # 内存存储（MVP），后续替换为数据库
        self._escrows: dict[str, Escrow] = {}
    
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
        )
        
        self._escrows[job_id] = escrow
        return escrow
    
    def get_escrow(self, job_id: str) -> Optional[Escrow]:
        """获取 Escrow"""
        return self._escrows.get(job_id)
    
    def execute_settlement(self, request: SettlementRequest) -> Escrow:
        """
        执行结算
        
        分配:
        - Node: 95%
        - System: 5%
        - 余额: 退还 Buyer
        """
        escrow = None
        for e in self._escrows.values():
            if e.job_id == request.match_id or e.match_id == request.match_id:
                escrow = e
                break
        
        if not escrow:
            raise ValueError(f"Escrow not found for match_id: {request.match_id}")
        
        # 计算实际费用
        actual_cost = self._calculate_cost(
            request.locked_price, request.actual_tokens
        )
        
        # 轻微延迟超标：降价结算
        if request.is_mild_latency_penalty:
            actual_cost *= settings.mild_latency_penalty  # 0.7
        
        # 结算分配
        platform_fee = actual_cost * settings.platform_fee_rate  # 5%
        node_earn = actual_cost * settings.node_earn_rate  # 95%
        refund_amount = escrow.locked_amount - actual_cost
        
        # 更新 Escrow
        escrow.spent_amount = actual_cost
        escrow.refund_amount = max(0, refund_amount)
        escrow.actual_tokens = request.actual_tokens
        escrow.actual_cost = actual_cost
        escrow.platform_fee = platform_fee
        escrow.node_earn = node_earn
        escrow.status = EscrowStatus.SETTLED
        escrow.settled_at = datetime.utcnow()
        
        return escrow
    
    def refund(self, job_id: str, reason: str) -> Escrow:
        """
        全额退款
        """
        escrow = self._escrows.get(job_id)
        if not escrow:
            raise ValueError(f"Escrow not found for job_id: {job_id}")
        
        escrow.refund_amount = escrow.locked_amount
        escrow.status = EscrowStatus.REFUNDED
        escrow.refunded_at = datetime.utcnow()
        escrow.refund_reason = reason
        
        return escrow
    
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
