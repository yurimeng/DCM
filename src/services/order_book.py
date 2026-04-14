"""
Order Book - F3.2: 订单簿（按 Model Family 分桶）
来源: Function/F3-Match-Engine-2.0 Section F3.2
"""

from typing import Dict, List, Optional
from collections import defaultdict
import time

from ..models.cluster import Cluster, ClusterStatus, ModelInfo
from ..models.job import Job, JobStatus


class OrderBook:
    """
    订单簿 - 按 Model Family 分桶
    
    结构:
    {
        "qwen": {
            "clusters": [...],  # 可用 Cluster 列表（按价格升序）
            "jobs": [...],   # 待撮合 Job 列表（按价格降序）
        },
        "llama": {...},
        "*": {...}  # 通用（无 model 要求）
    }
    """
    
    def __init__(self):
        # 按 family 分桶: family -> {clusters: [], jobs: []}
        self._buckets: Dict[str, Dict[str, List]] = defaultdict(lambda: {
            "clusters": [],   # Cluster 列表
            "jobs": [],    # Job 列表
        })
        # 全局桶（通用任务）
        self._generic_bucket = {"clusters": [], "jobs": []}
    
    def _get_bucket_key(self, family: Optional[str]) -> str:
        """获取桶的 key"""
        if not family:
            return "*"
        return family.lower()
    
    # ==================== Cluster 管理 ====================
    
    def add_cluster(self, cluster: Cluster) -> None:
        """添加 Cluster 到 Order Book"""
        family = cluster.model.family.lower()
        bucket = self._buckets[family]
        
        # 检查是否已存在
        if any(c.cluster_id == cluster.cluster_id for c in bucket["clusters"]):
            return
        
        # 按价格升序插入（保持排序）
        clusters = bucket["clusters"]
        inserted = False
        for i, c in enumerate(clusters):
            if cluster.pricing.output_price < c.pricing.output_price:
                clusters.insert(i, cluster)
                inserted = True
                break
        
        if not inserted:
            clusters.append(cluster)
        
        # 通用桶也添加（通用任务可以匹配任何 cluster）
        if cluster not in self._generic_bucket["clusters"]:
            self._generic_bucket["clusters"].append(cluster)
    
    # 别名兼容
    def add_slot(self, cluster: Cluster) -> None:
        """添加 Slot 到 Order Book (兼容别名)"""
        return self.add_cluster(cluster)
    
    def remove_cluster(self, cluster_id: str) -> Optional[Cluster]:
        """从 Order Book 移除 Cluster"""
        removed = None
        
        # 从各桶中移除
        for bucket in list(self._buckets.values()) + [self._generic_bucket]:
            for i, c in enumerate(bucket["clusters"]):
                if c.cluster_id == cluster_id:
                    removed = bucket["clusters"].pop(i)
                    break
        
        return removed
    
    # 别名兼容
    def remove_slot(self, cluster_id: str) -> Optional[Cluster]:
        """从 Order Book 移除 Slot (兼容别名)"""
        return self.remove_cluster(cluster_id)
    
    def update_cluster(self, cluster: Cluster) -> None:
        """更新 Cluster（状态变化后重新排序）"""
        self.remove_cluster(cluster.cluster_id)
        if cluster.status == ClusterStatus.FREE:
            self.add_cluster(cluster)
    
    # 别名兼容
    def update_slot(self, cluster: Cluster) -> None:
        """更新 Slot (兼容别名)"""
        return self.update_cluster(cluster)
    
    def get_clusters(self, family: Optional[str] = None) -> List[Cluster]:
        """获取指定 family 的 Clusters"""
        if not family:
            return list(self._generic_bucket["clusters"])
        return list(self._buckets.get(family.lower(), {}).get("clusters", []))
    
    # 别名兼容
    def get_slots(self, family: Optional[str] = None) -> List[Cluster]:
        """获取指定 family 的 Slots (兼容别名)"""
        return self.get_clusters(family)
    
    def get_all_clusters(self) -> List[Cluster]:
        """获取所有 Clusters（去重）"""
        seen = set()
        result = []
        for bucket in self._buckets.values():
            for cluster in bucket["clusters"]:
                if cluster.cluster_id not in seen:
                    seen.add(cluster.cluster_id)
                    result.append(cluster)
        return result
    
    # 别名兼容
    def get_all_slots(self) -> List[Cluster]:
        """获取所有 Slots (兼容别名)"""
        return self.get_all_clusters()
    
    # ==================== Job 管理 ====================
    
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
    
    def get_jobs(self, family: Optional[str] = None) -> List[Job]:
        """获取指定 family 的 Jobs"""
        if not family:
            return list(self._generic_bucket["jobs"])
        return list(self._buckets.get(family.lower(), {}).get("jobs", []))
    
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
    
    # ==================== 统计 ====================
    
    def get_bucket_stats(self) -> Dict[str, Dict[str, int]]:
        """获取各桶统计信息"""
        stats = {}
        for family, bucket in self._buckets.items():
            stats[family] = {
                "clusters_count": len(bucket["clusters"]),
                "jobs_count": len(bucket["jobs"]),
            }
        stats["*"] = {
            "clusters_count": len(self._generic_bucket["clusters"]),
            "jobs_count": len(self._generic_bucket["jobs"]),
        }
        return stats
    
    def clear(self) -> None:
        """清空 Order Book"""
        self._buckets.clear()
        self._generic_bucket = {"clusters": [], "jobs": []}
