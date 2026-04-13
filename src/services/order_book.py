"""
Order Book - F3.2: 订单簿（按 Model Family 分桶）
来源: Function/F3-Match-Engine-2.0 Section F3.2
"""

from typing import Dict, List, Optional
from collections import defaultdict
import time

from ..models.slot import Slot, SlotStatus, ModelInfo
from ..models.job import Job, JobStatus


class OrderBook:
    """
    订单簿 - 按 Model Family 分桶
    
    结构:
    {
        "qwen": {
            "slots": [...],  # 可用 Slot 列表（按价格升序）
            "jobs": [...],   # 待撮合 Job 列表（按价格降序）
        },
        "llama": {...},
        "*": {...}  # 通用（无 model 要求）
    }
    """
    
    def __init__(self):
        # 按 family 分桶: family -> {slots: [], jobs: []}
        self._buckets: Dict[str, Dict[str, List]] = defaultdict(lambda: {
            "slots": [],   # Slot 列表
            "jobs": [],    # Job 列表
        })
        # 全局桶（通用任务）
        self._generic_bucket = {"slots": [], "jobs": []}
    
    def _get_bucket_key(self, family: Optional[str]) -> str:
        """获取桶的 key"""
        if not family:
            return "*"
        return family.lower()
    
    def add_slot(self, slot: Slot) -> None:
        """添加 Slot 到 Order Book"""
        family = slot.model.family.lower()  # 直接使用 family 字段
        bucket = self._buckets[family]
        
        # 检查是否已存在
        if any(s.slot_id == slot.slot_id for s in bucket["slots"]):
            return
        
        # 按价格升序插入（保持排序）
        slots = bucket["slots"]
        inserted = False
        for i, s in enumerate(slots):
            if slot.pricing.output_price < s.pricing.output_price:
                slots.insert(i, slot)
                inserted = True
                break
        
        if not inserted:
            slots.append(slot)
        
        # 通用桶也添加（通用任务可以匹配任何 slot）
        if slot not in self._generic_bucket["slots"]:
            self._generic_bucket["slots"].append(slot)
    
    def remove_slot(self, slot_id: str) -> Optional[Slot]:
        """从 Order Book 移除 Slot"""
        removed = None
        
        # 从各桶中移除
        for bucket in list(self._buckets.values()) + [self._generic_bucket]:
            for i, s in enumerate(bucket["slots"]):
                if s.slot_id == slot_id:
                    removed = bucket["slots"].pop(i)
                    break
        
        return removed
    
    def update_slot(self, slot: Slot) -> None:
        """更新 Slot（状态变化后重新排序）"""
        self.remove_slot(slot.slot_id)
        if slot.status == SlotStatus.FREE:
            self.add_slot(slot)
    
    def add_job(self, job: Job) -> None:
        """添加 Job 到 Order Book"""
        import re
        family = None
        if job.model_requirement:
            # 从 model 字符串解析 family
            base = job.model_requirement.split(":")[0]
            match = re.match(r'^([a-zA-Z]+)', base)
            family = match.group(1).lower() if match else base.lower()
        
        bucket_key = self._get_bucket_key(family)
        bucket = self._buckets[bucket_key]
        
        # 检查是否已存在
        if any(j.job_id == job.job_id for j in bucket["jobs"]):
            return
        
        # 按价格降序插入（出价高的优先）
        jobs = bucket["jobs"]
        inserted = False
        for i, j in enumerate(jobs):
            if job.bid_price > j.bid_price:
                jobs.insert(i, job)
                inserted = True
                break
        
        if not inserted:
            jobs.append(job)
        
        # 通用任务也添加到通用桶
        if bucket_key == "*" and job not in self._generic_bucket["jobs"]:
            self._generic_bucket["jobs"].append(job)
    
    def remove_job(self, job_id: str) -> Optional[Job]:
        """从 Order Book 移除 Job"""
        removed = None
        
        for bucket in list(self._buckets.values()) + [self._generic_bucket]:
            for i, j in enumerate(bucket["jobs"]):
                if j.job_id == job_id:
                    removed = bucket["jobs"].pop(i)
                    break
        
        return removed
    
    def get_slots(self, family: Optional[str] = None) -> List[Slot]:
        """获取指定 family 的 Slots"""
        if not family:
            return list(self._generic_bucket["slots"])
        return list(self._buckets.get(family.lower(), {}).get("slots", []))
    
    def get_jobs(self, family: Optional[str] = None) -> List[Job]:
        """获取指定 family 的 Jobs"""
        if not family:
            return list(self._generic_bucket["jobs"])
        return list(self._buckets.get(family.lower(), {}).get("jobs", []))
    
    def get_all_slots(self) -> List[Slot]:
        """获取所有 Slots（去重）"""
        seen = set()
        result = []
        for bucket in self._buckets.values():
            for slot in bucket["slots"]:
                if slot.slot_id not in seen:
                    seen.add(slot.slot_id)
                    result.append(slot)
        return result
    
    def get_all_jobs(self) -> List[Job]:
        """获取所有 Jobs（去重）"""
        seen = set()
        result = []
        for bucket in self._buckets.values():
            for job in bucket["jobs"]:
                if job.job_id not in seen:
                    seen.add(job.job_id)
                    result.append(job)
        return result
    
    def get_bucket_stats(self) -> Dict[str, Dict[str, int]]:
        """获取各桶统计信息"""
        stats = {}
        for family, bucket in self._buckets.items():
            stats[family] = {
                "slots_count": len(bucket["slots"]),
                "jobs_count": len(bucket["jobs"]),
            }
        stats["*"] = {
            "slots_count": len(self._generic_bucket["slots"]),
            "jobs_count": len(self._generic_bucket["jobs"]),
        }
        return stats
    
    def clear(self) -> None:
        """清空 Order Book"""
        self._buckets.clear()
        self._generic_bucket = {"slots": [], "jobs": []}
