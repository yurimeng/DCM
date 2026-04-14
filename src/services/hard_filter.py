"""
Hard Filter - DCM v3.2
Based on Node Live Status Report
"""

from typing import Optional, List, Tuple
from ..models.node import Node
from ..models.job import Job
from .node_status_store import node_status_store, NodeStatusStore


class HardFilter:
    """Hard Filter - DCM v3.2"""

    def __init__(self, status_store: Optional[NodeStatusStore] = None):
        self.status_store = status_store or node_status_store

    def filter(self, cluster_or_node, job: Job) -> Tuple[bool, Optional[str]]:
        """Filter single Cluster/Node (compatible interface)"""
        from ..models.cluster import Cluster

        if isinstance(cluster_or_node, Node):
            return self.filter_node(cluster_or_node, job)
        elif isinstance(cluster_or_node, Cluster):
            return self._filter_cluster(cluster_or_node, job)

        return False, "unsupported_type"

    def filter_node(self, node: Node, job: Job) -> Tuple[bool, Optional[str]]:
        """Filter single Node"""
        live_status = self.status_store.get_node_status(node.node_id)
        available_concurrency = live_status["available_concurrency"]
        available_queue_tokens = live_status["available_queue_tokens"]

        job_tokens = job.input_tokens + job.output_tokens_limit

        if available_concurrency <= 0:
            return False, "no_available_concurrency"
        if available_queue_tokens < job_tokens:
            return False, "insufficient_queue_tokens"
        if node.pricing.ask_price_usdc_per_mtoken > job.bid_price:
            return False, "price_too_high"

        if job.model_requirement:
            model_found = any(
                job.model_requirement.lower() in model.lower()
                for model in node.runtime.loaded_models
            )
            if not model_found:
                job_family = job.model_requirement.split(":")[0].lower()
                family_found = any(
                    job_family in model.lower()
                    for model in node.runtime.loaded_models
                )
                if not family_found:
                    return False, "model_not_supported"

        return True, None

    def _filter_cluster(self, cluster, job: Job) -> Tuple[bool, Optional[str]]:
        """Filter Cluster (simplified)"""
        live_status = self.status_store.get_node_status(cluster.cluster_id)
        available_concurrency = live_status["available_concurrency"]
        available_queue_tokens = live_status["available_queue_tokens"]

        job_tokens = job.input_tokens + job.output_tokens_limit

        if available_concurrency <= 0:
            return False, "no_available_concurrency"
        if available_queue_tokens < job_tokens:
            return False, "insufficient_queue_tokens"
        if cluster.pricing.output_price > job.bid_price:
            return False, "output_price_too_high"
        if cluster.performance.avg_latency_ms > job.max_latency:
            return False, "latency_too_high"

        # Model compatibility check
        if job.model_requirement:
            cluster_model = cluster.model.name
            if job.model_requirement.lower() not in cluster_model.lower():
                job_family = job.model_requirement.split(":")[0].lower()
                cluster_family = cluster.model.family.lower()
                if job_family != cluster_family:
                    return False, "model_not_supported"

        return True, None

    def filter_many(self, clusters_or_nodes, job: Job) -> list:
        """Batch filter (compatible interface)"""
        result = []
        for item in clusters_or_nodes:
            passed, _ = self.filter(item, job)
            if passed:
                result.append(item)
        return result

    def filter_many_nodes(self, nodes: List[Node], job: Job) -> List[Tuple[Node, Optional[str]]]:
        """Batch filter Nodes"""
        result = []
        for node in nodes:
            passed, reason = self.filter_node(node, job)
            result.append((node, reason))
        return result

    def get_passing_nodes(self, nodes: List[Node], job: Job) -> List[Node]:
        """Get passing Nodes"""
        return [node for node, reason in self.filter_many_nodes(nodes, job) if reason is None]


def create_default_filter() -> HardFilter:
    """Create default filter"""
    return HardFilter()
