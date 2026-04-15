"""
Node Status Store - DCM v3.2
Node 实时状态存储，支持 Redis/InMemoryDB 两种后端

后端配置从 config.py 加载
"""

from typing import Optional, Dict, List, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import time


def _get_config():
    """延迟加载配置"""
    from config import settings
    return settings


class NodeStatusBackend(ABC):
    """Node 状态存储后端接口"""
    
    @abstractmethod
    def update(self, node_id: str, status: Dict) -> None:
        """更新 Node 状态"""
        pass
    
    @abstractmethod
    def get(self, node_id: str) -> Optional[Dict]:
        """获取 Node 状态"""
        pass
    
    @abstractmethod
    def delete(self, node_id: str) -> None:
        """删除 Node 状态"""
        pass
    
    @abstractmethod
    def get_all(self) -> Dict[str, Dict]:
        """获取所有 Node 状态"""
        pass


class InMemoryNodeStatus(NodeStatusBackend):
    """内存存储后端（单机）"""
    
    def __init__(self):
        self._status: Dict[str, Dict] = {}
    
    def update(self, node_id: str, status: Dict) -> None:
        self._status[node_id] = {
            "timestamp": status.get("timestamp", int(time.time() * 1000)),
            "status": status.get("status", {}),
            "capacity": status.get("capacity", {}),
            "load": status.get("load", {}),
        }
    
    def get(self, node_id: str) -> Optional[Dict]:
        return self._status.get(node_id)
    
    def delete(self, node_id: str) -> None:
        self._status.pop(node_id, None)
    
    def get_all(self) -> Dict[str, Dict]:
        return self._status.copy()


class RedisNodeStatus(NodeStatusBackend):
    """Redis 存储后端（分布式）"""
    
    def __init__(self, redis_client=None, ttl_seconds: int = 30):
        self._redis = redis_client
        self._prefix = "dcm:node_status:"
        self._ttl = ttl_seconds
    
    def _key(self, node_id: str) -> str:
        return f"{self._prefix}{node_id}"
    
    def update(self, node_id: str, status: Dict) -> None:
        if self._redis:
            import json
            key = self._key(node_id)
            data = {
                "timestamp": status.get("timestamp", int(time.time() * 1000)),
                "status": status.get("status", {}),
                "capacity": status.get("capacity", {}),
                "load": status.get("load", {}),
            }
            self._redis.setex(key, self._ttl, json.dumps(data))
    
    def get(self, node_id: str) -> Optional[Dict]:
        if self._redis:
            import json
            key = self._key(node_id)
            data = self._redis.get(key)
            if data:
                return json.loads(data)
        return None
    
    def delete(self, node_id: str) -> None:
        if self._redis:
            self._redis.delete(self._key(node_id))
    
    def get_all(self) -> Dict[str, Dict]:
        if self._redis:
            import json
            keys = self._redis.keys(f"{self._prefix}*")
            result = {}
            for key in keys:
                node_id = key.decode() if isinstance(key, bytes) else key
                node_id = node_id.replace(self._prefix, "")
                data = self._redis.get(key)
                if data:
                    result[node_id] = json.loads(data)
            return result
        return {}


# ===== 数据结构定义 =====

class NodeStatusType(str, Enum):
    """节点状态类型"""
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"
    LOCKED = "locked"


@dataclass
class NodeStatusInfo:
    """节点状态信息（完整结构）"""
    node_id: str
    is_online: bool = False
    last_update_ms: int = 0
    status: str = "offline"
    available_concurrency: int = 0
    available_queue_tokens: int = 0
    active_jobs: int = 0
    vram_used_gb: float = 0.0
    vram_total_gb: float = 0.0
    cluster_id: Optional[str] = None
    # 原始数据
    raw_data: Dict = field(default_factory=dict)
    
    @property
    def age_seconds(self) -> float:
        """距上次更新的秒数"""
        import time
        if not self.last_update_ms:
            return float('inf')
        return (int(time.time() * 1000) - self.last_update_ms) / 1000
    
    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "is_online": self.is_online,
            "last_update_ms": self.last_update_ms,
            "age_seconds": round(self.age_seconds, 2),
            "status": self.status,
            "available_concurrency": self.available_concurrency,
            "available_queue_tokens": self.available_queue_tokens,
            "active_jobs": self.active_jobs,
            "vram_used_gb": self.vram_used_gb,
            "vram_total_gb": self.vram_total_gb,
            "cluster_id": self.cluster_id,
        }


@dataclass
class NodeListFilter:
    """节点列表过滤条件"""
    # 在线状态
    online_only: bool = False
    max_age_seconds: int = 10
    
    # 容量要求
    min_concurrency: int = 0
    min_queue_tokens: int = 0
    
    # 集群过滤
    cluster_id: Optional[str] = None
    
    # 指定节点列表
    node_ids: Optional[List[str]] = None
    
    # 自定义过滤函数
    filter_func: Optional[Callable[[NodeStatusInfo], bool]] = None
    
    # 排序
    sort_by: str = "node_id"  # node_id, age_seconds, available_concurrency
    sort_reverse: bool = False


class NodeStatusStore:
    """
    Node 实时状态存储
    
    提供统一的接口访问 Node Live Status Report 数据
    
    使用方式:
    1. Node Agent 发送 status report 时调用 update()
    2. Match Engine 匹配时调用 get_node_status()
    3. 获取节点列表使用 list_nodes()
    """
    
    def __init__(self, backend: Optional[NodeStatusBackend] = None):
        self._backend = backend or InMemoryNodeStatus()
    
    def set_backend(self, backend: NodeStatusBackend) -> None:
        """切换存储后端"""
        self._backend = backend
    
    def update(self, node_id: str, status: Dict) -> None:
        """更新 Node 实时状态
        
        Args:
            node_id: Node ID
            status: Node Live Status Report 数据
        """
        self._backend.update(node_id, status)
    
    def get(self, node_id: str) -> Optional[Dict]:
        """获取 Node 原始状态
        
        Args:
            node_id: Node ID
            
        Returns:
            原始状态 dict 或 None
        """
        return self._backend.get(node_id)
    
    def get_node_status(self, node_id: str) -> Dict:
        """获取 Node 解析后的状态（带默认值）
        
        Args:
            node_id: Node ID
            
        Returns:
            解析后的状态
        """
        status = self._backend.get(node_id)
        if not status:
            return {
                "available_concurrency": 0,
                "available_queue_tokens": 0,
                "active_jobs": 0,
                "vram_used_gb": 0,
                "vram_total_gb": 0,
            }
        
        cap = status.get("capacity", {})
        load = status.get("load", {})
        st = status.get("status", {})
        
        return {
            "available_concurrency": cap.get("max_concurrency_available", 0),
            "available_queue_tokens": load.get("available_token_capacity", 0),
            "active_jobs": load.get("active_jobs", 0),
            "vram_used_gb": st.get("vram_used_gb", 0),
            "vram_total_gb": st.get("vram_total_gb", 0),
            "timestamp": status.get("timestamp", 0),
        }
    
    def delete(self, node_id: str) -> None:
        """删除 Node 状态（Node 离线时调用）"""
        self._backend.delete(node_id)
    
    def get_all(self) -> Dict[str, Dict]:
        """获取所有 Node 状态"""
        return self._backend.get_all()
    
    def get_available_nodes(self, min_concurrency: int = 1, min_queue_tokens: int = 1) -> list:
        """获取所有可用的 Nodes
        
        Args:
            min_concurrency: 最小并发要求
            min_queue_tokens: 最小队列 token 要求
            
        Returns:
            可用 Node 列表
        """
        available = []
        for node_id, status in self.get_all().items():
            cap = status.get("capacity", {})
            load = status.get("load", {})
            
            if cap.get("max_concurrency_available", 0) >= min_concurrency:
                if load.get("available_token_capacity", 0) >= min_queue_tokens:
                    available.append(node_id)
        
        return available

    def is_online(self, node_id: str, max_age_seconds: int = 10) -> bool:
        """
        检查 Node 是否在线（最近 N 秒有更新）
        
        Args:
            node_id: Node ID
            max_age_seconds: 最大间隔秒数（默认10秒）
            
        Returns:
            True if node has recent status update
        """
        status = self.get(node_id)
        if not status:
            return False
        
        timestamp = status.get("timestamp", 0)
        if not timestamp:
            return False
        
        import time
        current_time_ms = int(time.time() * 1000)
        age_seconds = (current_time_ms - timestamp) / 1000
        
        return age_seconds <= max_age_seconds
    
    # ===== 通用节点列表查询 =====
    
    def _parse_node_status(self, node_id: str, raw_status: Optional[Dict]) -> NodeStatusInfo:
        """解析原始状态为 NodeStatusInfo"""
        if not raw_status:
            return NodeStatusInfo(node_id=node_id, is_online=False)
        
        import time
        timestamp = raw_status.get("timestamp", 0)
        current_time_ms = int(time.time() * 1000)
        age_seconds = (current_time_ms - timestamp) / 1000 if timestamp else float('inf')
        
        cap = raw_status.get("capacity", {})
        load = raw_status.get("load", {})
        st = raw_status.get("status", {})
        
        return NodeStatusInfo(
            node_id=node_id,
            is_online=age_seconds <= 10,  # 10秒内更新视为在线
            last_update_ms=timestamp,
            status=st.get("status", "unknown"),
            available_concurrency=cap.get("max_concurrency_available", 0),
            available_queue_tokens=load.get("available_token_capacity", 0),
            active_jobs=load.get("active_jobs", 0),
            vram_used_gb=st.get("vram_used_gb", 0.0),
            vram_total_gb=st.get("vram_total_gb", 0.0),
            cluster_id=raw_status.get("cluster_id"),
            raw_data=raw_status,
        )
    
    def list_nodes(
        self,
        filter: Optional[NodeListFilter] = None,
    ) -> List[NodeStatusInfo]:
        """
        通用节点列表查询
        
        Args:
            filter: 过滤条件，None 则返回所有节点
            
        Returns:
            节点状态信息列表
            
        使用示例:
            # 获取所有在线节点
            store.list_nodes(NodeListFilter(online_only=True))
            
            # 获取指定节点列表
            store.list_nodes(NodeListFilter(node_ids=["id1", "id2"]))
            
            # 获取某个集群的在线节点
            store.list_nodes(NodeListFilter(cluster_id="cluster-1", online_only=True))
            
            # 获取有可用容量的节点
            store.list_nodes(NodeListFilter(min_concurrency=1, min_queue_tokens=100))
            
            # 自定义过滤
            store.list_nodes(NodeListFilter(
                filter_func=lambda n: n.vram_used_gb < 10
            ))
        """
        if filter is None:
            filter = NodeListFilter()
        
        # 获取所有原始状态
        all_status = self.get_all()
        
        # 如果指定了 node_ids，先过滤
        if filter.node_ids:
            filtered = {nid: all_status.get(nid) for nid in filter.node_ids if nid in all_status}
        else:
            filtered = all_status
        
        # 解析为 NodeStatusInfo
        nodes = [self._parse_node_status(node_id, status) for node_id, status in filtered.items()]
        
        # 应用过滤条件
        if filter.online_only:
            nodes = [n for n in nodes if n.is_online]
        
        if filter.max_age_seconds < 10:
            # 更严格的在线检查
            import time
            nodes = [n for n in nodes if n.last_update_ms == 0 or 
                    (int(time.time() * 1000) - n.last_update_ms) / 1000 <= filter.max_age_seconds]
        
        if filter.min_concurrency > 0:
            nodes = [n for n in nodes if n.available_concurrency >= filter.min_concurrency]
        
        if filter.min_queue_tokens > 0:
            nodes = [n for n in nodes if n.available_queue_tokens >= filter.min_queue_tokens]
        
        if filter.cluster_id:
            nodes = [n for n in nodes if n.cluster_id == filter.cluster_id]
        
        if filter.filter_func:
            nodes = [n for n in nodes if filter.filter_func(n)]
        
        # 排序
        sort_key = {
            "node_id": lambda n: n.node_id,
            "age_seconds": lambda n: n.age_seconds,
            "available_concurrency": lambda n: n.available_concurrency,
        }.get(filter.sort_by, lambda n: n.node_id)
        
        nodes.sort(key=sort_key, reverse=filter.sort_reverse)
        
        return nodes
    
    def list_online_nodes(
        self,
        max_age_seconds: int = 10,
        min_concurrency: int = 0,
        min_queue_tokens: int = 0,
        cluster_id: Optional[str] = None,
    ) -> List[NodeStatusInfo]:
        """
        获取在线节点列表（便捷方法）
        
        Args:
            max_age_seconds: 最大更新时间间隔
            min_concurrency: 最小并发要求
            min_queue_tokens: 最小队列容量要求
            cluster_id: 集群 ID 过滤
            
        Returns:
            在线节点列表
        """
        return self.list_nodes(NodeListFilter(
            online_only=True,
            max_age_seconds=max_age_seconds,
            min_concurrency=min_concurrency,
            min_queue_tokens=min_queue_tokens,
            cluster_id=cluster_id,
        ))
    
    def get_node_info(self, node_id: str) -> NodeStatusInfo:
        """
        获取单个节点的完整状态信息
        
        Args:
            node_id: Node ID
            
        Returns:
            节点状态信息
        """
        raw = self.get(node_id)
        return self._parse_node_status(node_id, raw)


# ===== 全局实例（延迟初始化）=====

_node_status_store: Optional[NodeStatusStore] = None


def get_node_status_store() -> NodeStatusStore:
    """获取全局 NodeStatusStore 实例（延迟初始化）"""
    global _node_status_store
    if _node_status_store is None:
        _node_status_store = _create_from_config()
    return _node_status_store


def _create_from_config() -> NodeStatusStore:
    """从配置创建 NodeStatusStore"""
    config = _get_config()
    
    backend_type = config.node_status_store_backend.lower()
    
    if backend_type == "redis":
        try:
            import redis
            # 从环境变量获取 Redis URL
            redis_url = config.database_url
            client = redis.from_url(redis_url)
            backend = RedisNodeStatus(client, ttl_seconds=config.node_status_store_ttl_seconds)
            return NodeStatusStore(backend)
        except Exception as e:
            print(f"Warning: Failed to init Redis backend: {e}, falling back to memory")
            return NodeStatusStore(InMemoryNodeStatus())
    else:
        return NodeStatusStore(InMemoryNodeStatus())


# Match Engine 使用（延迟初始化）
node_status_store = get_node_status_store()

# 便捷函数
def update_node_status(node_id: str, status: Dict, capacity_info: Optional[Dict] = None) -> Optional[str]:
    """
    更新 Node 实时状态
    
    如果提供了 capacity_info，会自动生成并返回 cluster_id
    
    Args:
        node_id: Node ID
        status: Node Live Status Report 数据
        capacity_info: 容量信息（用于生成 cluster_id）
            - runtime: {"type": "ollama", "loaded_models": ["qwen2.5:7b"]}
            - region: str
            - stake_tier: str
    
    Returns:
        生成的 cluster_id 或 None
    """
    cluster_id = None
    
    # 如果提供了 capacity_info，生成 cluster_id
    if capacity_info:
        try:
            from .cluster_builder import build_cluster_id
            
            # 获取 models
            models = []
            if capacity_info.get("runtime"):
                models = capacity_info["runtime"].get("loaded_models", [])
            elif capacity_info.get("models"):
                models = capacity_info.get("models", [])
            
            if models:
                cluster_id = build_cluster_id(
                    region=capacity_info.get("region", "unknown"),
                    stake_tier=capacity_info.get("stake_tier", "personal"),
                    models=models,
                    quality_score=capacity_info.get("quality_score", 0.9),
                    success_rate=capacity_info.get("success_rate", 0.95),
                )
                # 将 cluster_id 加入 status
                status = {**status, "cluster_id": cluster_id}
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to build cluster_id: {e}")
    
    node_status_store.update(node_id, status)
    return cluster_id


def get_node_status(node_id: str) -> Dict:
    """获取 Node 状态"""
    return node_status_store.get_node_status(node_id)


def get_node_status(node_id: str) -> Dict:
    """获取 Node 状态"""
    return node_status_store.get_node_status(node_id)


def get_all_node_status() -> Dict[str, Dict]:
    """获取所有 Node 状态"""
    return node_status_store.get_all()


def init_redis_backend(redis_client) -> None:
    """初始化 Redis 后端"""
    node_status_store.set_backend(RedisNodeStatus(redis_client))


# ===== 通用节点列表查询便捷函数 =====

def list_nodes(
    online_only: bool = False,
    max_age_seconds: int = 10,
    min_concurrency: int = 0,
    min_queue_tokens: int = 0,
    cluster_id: Optional[str] = None,
    node_ids: Optional[List[str]] = None,
) -> List[NodeStatusInfo]:
    """
    通用节点列表查询便捷函数
    
    Args:
        online_only: 只返回在线节点
        max_age_seconds: 最大更新时间间隔（秒）
        min_concurrency: 最小并发要求
        min_queue_tokens: 最小队列容量要求
        cluster_id: 集群 ID 过滤
        node_ids: 指定节点 ID 列表
        
    Returns:
        节点状态信息列表
        
    使用示例:
        # 获取所有在线节点
        list_nodes(online_only=True)
        
        # 获取指定节点列表
        list_nodes(node_ids=["id1", "id2"])
        
        # 获取有可用容量的在线节点
        list_nodes(online_only=True, min_concurrency=1)
    """
    return node_status_store.list_nodes(NodeListFilter(
        online_only=online_only,
        max_age_seconds=max_age_seconds,
        min_concurrency=min_concurrency,
        min_queue_tokens=min_queue_tokens,
        cluster_id=cluster_id,
        node_ids=node_ids,
    ))


def list_online_nodes(
    max_age_seconds: int = 10,
    min_concurrency: int = 0,
    min_queue_tokens: int = 0,
    cluster_id: Optional[str] = None,
) -> List[NodeStatusInfo]:
    """
    获取在线节点列表（便捷函数）
    
    Args:
        max_age_seconds: 最大更新时间间隔
        min_concurrency: 最小并发要求
        min_queue_tokens: 最小队列容量要求
        cluster_id: 集群 ID 过滤
        
    Returns:
        在线节点列表
    """
    return node_status_store.list_online_nodes(
        max_age_seconds=max_age_seconds,
        min_concurrency=min_concurrency,
        min_queue_tokens=min_queue_tokens,
        cluster_id=cluster_id,
    )


def get_node_info(node_id: str) -> NodeStatusInfo:
    """
    获取单个节点的完整状态信息
    
    Args:
        node_id: Node ID
        
    Returns:
        节点状态信息
    """
    return node_status_store.get_node_info(node_id)
