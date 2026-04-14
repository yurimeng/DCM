"""
Node Status Store - DCM v3.2
Node 实时状态存储，支持 Redis/InMemoryDB 两种后端

后端配置从 config.py 加载
"""

from typing import Optional, Dict
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


class NodeStatusStore:
    """
    Node 实时状态存储
    
    提供统一的接口访问 Node Live Status Report 数据
    
    使用方式:
    1. Node Agent 发送 status report 时调用 update()
    2. Match Engine 匹配时调用 get_node_status()
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
def update_node_status(node_id: str, status: Dict) -> None:
    """更新 Node 实时状态"""
    node_status_store.update(node_id, status)


def get_node_status(node_id: str) -> Dict:
    """获取 Node 状态"""
    return node_status_store.get_node_status(node_id)


def get_all_node_status() -> Dict[str, Dict]:
    """获取所有 Node 状态"""
    return node_status_store.get_all()


def init_redis_backend(redis_client) -> None:
    """初始化 Redis 后端"""
    node_status_store.set_backend(RedisNodeStatus(redis_client))
