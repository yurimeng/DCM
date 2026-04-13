"""
Hard Filter - F3.3: 硬过滤条件 + 模型兼容性
来源: Function/F3-Match-Engine-2.0 Section F3.3

硬过滤条件:
1. 模型兼容性检查 (新增)
2. Slot 状态必须是 FREE
3. 容量检查: current_load < max_concurrency
4. 价格检查: slot.price <= job.max_price
5. 延迟检查: slot.latency <= job.max_latency
6. 区域检查（可选）: slot.region == job.region
"""

from typing import Optional
from ..models.slot import Slot, SlotStatus
from ..models.job import Job, JobStatus
from .compatibility import CompatibilityMatrix, compatibility_matrix


class HardFilter:
    """
    硬过滤器 - 必须满足所有条件才能进入评分阶段
    
    过滤条件:
    1. 模型兼容性检查
    2. Slot 状态必须是 FREE
    3. 容量检查: current_load < max_concurrency
    4. 价格检查: slot.price <= job.max_price
    5. 延迟检查: slot.latency <= job.max_latency
    6. 区域检查（可选）: slot.region == job.region
    """
    
    def __init__(
        self,
        check_region: bool = False,
        compatibility: Optional[CompatibilityMatrix] = None,
    ):
        self.check_region = check_region
        self.compatibility = compatibility or compatibility_matrix
    
    def filter(self, slot: Slot, job: Job) -> tuple[bool, Optional[str]]:
        """
        执行硬过滤
        
        Args:
            slot: 待检查的 Slot
            job: 待检查的 Job
            
        Returns:
            (通过, 失败原因)
        """
        # 1. 模型兼容性检查
        job_model = job.model_requirement
        slot_model = slot.model.name
        compat_score = self.compatibility.get_compatibility(job_model, slot_model)
        if compat_score <= 0:
            return False, "model_incompatible"
        
        # 2. Slot 状态检查 (DCM v3.1: 允许 FREE, PRE_LOCKED, PARTIALLY_RESERVED)
        if slot.status not in [SlotStatus.FREE, SlotStatus.PRE_LOCKED, SlotStatus.PARTIALLY_RESERVED]:
            return False, "slot_not_available"
        
        # 3. 容量检查 (DCM v3.1: 使用 available_capacity)
        if slot.capacity.available_capacity <= 0:
            return False, "slot_at_capacity"
        
        # 4. 价格检查 - 输入价格
        if hasattr(job, 'max_input_price') and job.max_input_price:
            if slot.pricing.input_price > job.max_input_price:
                return False, "input_price_too_high"
        
        # 5. 价格检查 - 输出价格
        if slot.pricing.output_price > job.bid_price:
            return False, "output_price_too_high"
        
        # 6. 延迟检查
        if slot.performance.avg_latency_ms > job.max_latency:
            return False, "latency_too_high"
        
        # 7. 区域检查（可选）
        if self.check_region and job.region:
            if slot.region and slot.region != job.region:
                return False, "region_mismatch"
        
        return True, None
    
    def filter_many(self, slots: list[Slot], job: Job) -> list[Slot]:
        """
        批量过滤 Slots
        
        Args:
            slots: 待过滤的 Slots 列表
            job: 目标 Job
            
        Returns:
            通过过滤的 Slots 列表
        """
        result = []
        for slot in slots:
            passed, _ = self.filter(slot, job)
            if passed:
                result.append(slot)
        return result


def create_default_filter() -> HardFilter:
    """创建默认配置的过滤器"""
    return HardFilter(check_region=False)
