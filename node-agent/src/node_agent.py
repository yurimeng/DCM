"""
DCM Node Agent - Core Module
节点代理核心模块

Functions: Register / Heartbeat / Poll Jobs / Process and Return Results
功能：注册 / 心跳 / 轮询 Job / 处理并返回结果

Mandatory: Report runtime and model
强制要求：上报 runtime 和 model

Based on F16-Runtime-Adapter-Layer Architecture
基于 F16-Runtime-Adapter-Layer 架构

Supports Multi-Network Protocols: HTTPS, P2P, Relay
支持多网络协议：HTTPS, P2P, Relay
"""

import os
import json
import time
import uuid
import logging
import threading
import hashlib
import base64
import requests
from dataclasses import dataclass, field
from typing import Optional, Dict, Set, List
from pathlib import Path

from .runtime_adapter import RuntimeAdapter, create_runtime_adapter, ExecutionResult
from .network import (
    NetworkAdapter, NetworkConfig, NetworkType, NetworkState,
    Invoke, Result
)
from .system_info import get_system_info, SystemInfo, GPUInfo, OSInfo

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Supported runtime types
# 支持的运行时类型
SUPPORTED_RUNTIMES = ["ollama", "vllm", "tensorrt", "lmstudio"]


@dataclass
class NodeConfig:
    """
    Node Configuration (Required: runtime and model)
    节点配置（必填：runtime 和 model）
    
    User ID is required for authentication
    用户 ID 用于身份验证
    """
    # DCM API endpoint
    dcm_url: str = "https://dcm-api-p00a.onrender.com"
    
    # User ID (required for authentication)
    # 用户 ID（身份验证必需）
    user_id: Optional[str] = None
    
    # Unique node identifier / 节点唯一标识
    node_id: Optional[str] = None
    
    # ===== REQUIRED FIELDS / 必填字段 =====
    # Runtime type: ollama, vllm, tensorrt, lmstudio
    runtime: Optional[str] = None
    
    # Model name: qwen2.5:7b, llama3:8b, etc.
    model: Optional[str] = None
    
    # ===== OPTIONAL FIELDS / 可选字段 =====
    gpu_count: int = 1
    slot_count: int = 4
    worker_count: int = 2
    poll_interval: int = 3
    heartbeat_interval: int = 30
    stake_amount: float = 200.0
    
    # Network configuration / 网络配置
    network_enabled: bool = True
    p2p_enabled: bool = False
    relay_enabled: bool = False
    
    @classmethod
    def from_file(cls, path: str = ".node_agent_id") -> "NodeConfig":
        """
        Load configuration from file
        从文件加载配置
        """
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                logger.debug(f"Loaded config: {data}")
                return cls(**data)
        return cls()
    
    @classmethod
    def fetch_from_dcm(cls, dcm_url: str) -> dict:
        """
        Fetch available runtimes from DCM
        从 DCM 获取可用的运行时列表
        """
        import requests
        try:
            resp = requests.get(f"{dcm_url}/internal/v1/runtimes", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"Fetched runtimes from DCM: {list(data.get('runtimes', {}).keys())}")
                return data
            else:
                logger.error(f"Failed to fetch runtimes: {resp.status_code}")
                return {}
        except Exception as e:
            logger.error(f"Error fetching runtimes: {e}")
            return {}
    
    def get_runtime_endpoint(self) -> Optional[dict]:
        """
        Get runtime endpoint configuration from DCM
        从 DCM 获取运行时端点配置
        """
        if not self.runtime:
            return None
        
        runtimes_data = self.fetch_from_dcm(self.dcm_url)
        runtimes = runtimes_data.get("runtimes", {})
        
        return runtimes.get(self.runtime)
    
    def validate_required_fields(self) -> List[str]:
        """
        Validate required fields, return list of missing fields
        验证必填字段，返回缺失字段列表
        """
        missing = []
        if not self.user_id:
            missing.append("user_id")
        if not self.runtime:
            missing.append("runtime")
        if not self.model:
            missing.append("model")
        return missing
    
    @staticmethod
    def is_valid_uuid(user_id: str) -> bool:
        """
        Validate UUID format
        验证 UUID 格式
        """
        import re
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )
        return bool(uuid_pattern.match(user_id))
    
    def validate_user_id(self) -> tuple[bool, str]:
        """
        Validate user ID
        验证用户 ID
        
        Returns:
            (is_valid, error_message)
        """
        if not self.user_id:
            return False, "user_id is required"
        if not self.is_valid_uuid(self.user_id):
            return False, "Invalid user_id format (must be UUID)"
        return True, ""
    
    def validate_runtime(self) -> bool:
        """
        Validate runtime is supported
        验证运行时是否支持
        """
        if not self.runtime:
            return False
        return self.runtime.lower() in SUPPORTED_RUNTIMES
    
    def save(self, path: str = ".node_agent_id"):
        """
        Save configuration to file
        保存配置到文件
        """
        with open(path, 'w') as f:
            json.dump({
                "user_id": self.user_id,
                "node_id": self.node_id,
                "runtime": self.runtime,
                "model": self.model,
                "gpu_count": self.gpu_count,
                "slot_count": self.slot_count,
                "worker_count": self.worker_count,
                "dcm_url": self.dcm_url,
                "p2p_enabled": self.p2p_enabled,
                "relay_enabled": self.relay_enabled,
            }, f)


class DCMNodeAgent:
    """
    DCM Node Agent - Edge Execution Node
    DCM 节点代理 - 边缘执行节点
    
    Supports multi-network protocols:
    - HTTPS: Standard polling / 标准轮询
    - QUIC: HTTP/3 low latency / HTTP/3 低延迟
    - P2P: Peer-to-peer communication (gossipsub) / 点对点通信
    - Relay: NAT traversal / NAT 穿透
    
    Prompt delivery: P2P/Relay/QUIC (priority) / 优先
    Job/Settlement: HTTPS
    """
    
    def __init__(self, config: Optional[NodeConfig] = None):
        self.config = config or NodeConfig.from_file()
        
        # Determine primary network type
        # 确定首选网络类型
        primary_network = NetworkType.HTTPS
        if self.config.relay_enabled:
            primary_network = NetworkType.RELAY
        elif self.config.p2p_enabled:
            primary_network = NetworkType.P2P
        
        # Save preferred network for logging
        self._preferred_network = primary_network
        
        # Network adapter
        self.network = NetworkAdapter(NetworkConfig(
            primary=primary_network,
            https_endpoint=self.config.dcm_url,
            fallback_enabled=True,
            relay_enabled=self.config.relay_enabled,
            quic_enabled=True,
        ))
        
        # Original requested network type (for logging)
        self._requested_network: Optional[NetworkType] = None
        
        # Runtime adapter
        self.runtime = create_runtime_adapter({
            "backend": "ollama",
            "base_url": "http://localhost:11434"
        })
        
        # State / 状态
        self.processed_jobs: Set[str] = set()
        self.running = False
        self.lock = threading.Lock()
        
        # Network state monitoring
        self._setup_network_callbacks()
        
        # Ensure node ID persistence
        self._ensure_node_id()
    
    def _setup_network_callbacks(self):
        """Setup network callbacks / 设置网络回调"""
        def on_network_change(state: NetworkState, data: any):
            logger.info(f"Network state changed: {state.value}")
        
        self.network.register_callback("state_change", on_network_change)
    
    def _ensure_node_id(self):
        """
        Ensure node ID exists
        确保节点 ID 存在
        """
        if not self.config.node_id:
            cfg = NodeConfig.from_file()
            if cfg.node_id:
                self.config.node_id = cfg.node_id
                logger.info(f"Restored node ID: {self.config.node_id}")
    
    def _detect_region(self) -> str:
        """
        Detect region based on system info
        根据系统信息检测区域
        
        Default: "local" for edge devices
        默认为 "local"（边缘设备）
        """
        import socket
        
        try:
            # Try to determine region from hostname or domain
            hostname = socket.gethostname()
            
            # Check for common region indicators in hostname
            # 检查主机名中的常见区域标识
            if "us-" in hostname:
                return "us-west"
            elif "eu-" in hostname:
                return "eu-west"
            elif "asia-" in hostname:
                return "asia-east"
            elif "cn-" in hostname:
                return "cn-north"
            
            # Try to detect from timezone
            import time
            tz = time.tzname
            if "PST" in tz or "PDT" in tz:
                return "us-west"
            elif "EST" in tz or "EDT" in tz:
                return "us-east"
            elif "CET" in tz or "CEST" in tz:
                return "eu-west"
            
        except Exception:
            pass
        
        return "local"  # Default: local/edge node
    
    # ==================== Registration / 注册相关 ====================
    
    def check_node_exists(self) -> bool:
        """
        Check if node exists on server
        检查节点是否已存在于服务器
        """
        if not self.config.node_id:
            return False
        
        try:
            resp = requests.get(
                f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}",
                timeout=10
            )
            return resp.status_code == 200
        except:
            return False
    
    def register_node(self) -> bool:
        """
        Register new node (user_id, runtime and model are REQUIRED)
        注册新节点（user_id, runtime 和 model 是必填）
        """
        # Validate user_id / 验证用户 ID
        is_valid, error_msg = self.config.validate_user_id()
        if not is_valid:
            logger.error(f"User ID validation failed: {error_msg}")
            return False
        
        # Validate required fields / 验证必填字段
        missing = self.config.validate_required_fields()
        if missing:
            logger.error(f"Missing required fields: {missing}")
            logger.error(f"Please set user_id, runtime and model in config")
            return False
        
        if not self.config.validate_runtime():
            logger.error(f"Unsupported runtime: {self.config.runtime}")
            logger.error(f"Supported runtimes: {SUPPORTED_RUNTIMES}")
            return False
        
        try:
            # Detect system information / 检测系统信息
            system_info = get_system_info()
            
            # Build registration payload with system info
            # 使用系统信息构建注册载荷
            registration_payload = {
                # ===== USER AUTHENTICATION / 用户认证 =====
                "user_id": self.config.user_id,
                
                # GPU/Chipset info (chipset, qty, vram, pooled)
                # GPU/芯片组信息
                "chipset": system_info.gpu.chipset,
                "gpu_qty": system_info.gpu.qty,
                "gpu_vram_gb": system_info.gpu.vram_gb,
                "gpu_pooled": system_info.gpu.pooled,
                # OS info
                # 操作系统信息
                "os_name": system_info.os.name,
                "os_version": system_info.os.version,
                # Legacy fields for backward compatibility
                # 向下兼容的遗留字段
                "gpu_type": system_info.gpu.chipset,
                "vram_gb": int(system_info.gpu.vram_gb if system_info.gpu.vram_gb > 0 else system_info.total_memory_gb * 0.75),
                # ===== REQUIRED: runtime and model =====
                "runtime": self.config.runtime,
                "model": self.config.model,
                "model_support": [self.config.model],
                "ask_price": 0.000001,  # USDC per token
                "avg_latency": 200,
                "region": self._detect_region(),
                "gpu_count": system_info.gpu.qty,
            }
            
            logger.info(f"User ID: {self.config.user_id}")
            logger.info(f"System Info: {system_info}")
            logger.info(f"GPU: {system_info.gpu.chipset} x{system_info.gpu.qty}, VRAM={system_info.gpu.vram_gb}GB, Pooled={system_info.gpu.pooled}")
            logger.info(f"OS: {system_info.os.name} {system_info.os.version}")
            
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes",
                json=registration_payload,
                timeout=30
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.config.node_id = data["node_id"]
                self.config.save()
                logger.info(f"Node registered: {self.config.node_id}")
                return True
            else:
                logger.error(f"Registration failed: {resp.status_code} - {resp.text}")
                return False
        
        except Exception as e:
            logger.error(f"Registration exception: {e}")
            return False
    
    def ensure_online(self, max_retries: int = -1) -> bool:
        """
        Ensure node is online
        确保节点在线
        
        Args:
            max_retries: Maximum retry count, -1 means infinite
            
        If connection fails, retries every 30 seconds until success or max retries reached
        如果无法连接，每 30 秒重试一次，直到成功或达到最大重试次数
        """
        retry_count = 0
        retry_interval = 30
        
        while True:
            retry_count += 1
            
            # Try to connect network / 尝试连接网络
            if not self.network.connect():
                if max_retries > 0 and retry_count >= max_retries:
                    logger.error(f"Network connection failed after {retry_count} retries")
                    return False
                logger.warning(f"Network connection failed, retrying in {retry_interval}s... ({retry_count})")
                time.sleep(retry_interval)
                continue
            
            # Check if node exists / 检查节点是否存在
            if not self.check_node_exists():
                if not self.register_node():
                    if max_retries > 0 and retry_count >= max_retries:
                        logger.error(f"Node registration failed after {retry_count} retries")
                        return False
                    logger.warning(f"Node registration failed, retrying in {retry_interval}s... ({retry_count})")
                    time.sleep(retry_interval)
                    continue
            
            # Activate node as ONLINE / 激活节点为 ONLINE
            if not self.activate_online():
                logger.warning("Node activation failed")
            
            # Heartbeat check / 心跳检查
            if self.heartbeat():
                logger.info(f"Node online ({retry_count} attempts)")
                return True
            
            if max_retries > 0 and retry_count >= max_retries:
                logger.error(f"Heartbeat failed after {retry_count} retries")
                return False
            
            logger.warning(f"Heartbeat failed, retrying in {retry_interval}s... ({retry_count})")
            time.sleep(retry_interval)
    
    def activate_online(self) -> bool:
        """
        Activate node as ONLINE
        激活节点为 ONLINE
        """
        if not self.config.node_id:
            return False
        
        try:
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}/online",
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"Node activated: {data.get('status', 'online')}")
                return True
            else:
                logger.warning(f"Activation failed: {resp.status_code}")
                return False
        
        except Exception as e:
            logger.warning(f"Activation exception: {e}")
            return False
    
    def heartbeat(self) -> bool:
        """
        Send live_status and periodic capacity_report
        发送 live_status 和定期 capacity_report
        """
        if not self.config.node_id:
            return False
        
        try:
            # Increment report counter
            self._report_count = getattr(self, '_report_count', 0) + 1
            
            # === live_status (every call, ~3 seconds) ===
            live_status = {
                "timestamp": int(time.time() * 1000),
                "status": {
                    "status": "online",
                },
                "capacity": {
                    "max_concurrency_total": self.config.slot_count,
                    "max_concurrency_available": self.config.slot_count,
                },
                "load": {
                    "active_jobs": 0,
                    "available_token_capacity": 1500,
                },
            }
            
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}/live_status",
                json=live_status,
                timeout=10
            )
            
            if resp.status_code != 200:
                logger.warning(f"live_status failed: {resp.status_code}")
            
            # === capacity_report (every 30 calls, ~90 seconds) ===
            if self._report_count % 30 == 0:
                capacity_report = {
                    "timestamp": int(time.time() * 1000),
                    "runtime": {
                        "type": self.config.runtime,
                        "loaded_models": [self.config.model],
                    },
                    "ask_price": 0.000001,  # USDC per token
                    "avg_latency": 200,
                    "gpu_count": self.config.gpu_count,
                    "capacity": {
                        "max_concurrency_total": self.config.slot_count,
                    },
                }
                
                resp = requests.post(
                    f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}/capacity_report",
                    json=capacity_report,
                    timeout=10
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("new_cluster_id"):
                        logger.info(f"Cluster ID: {data['new_cluster_id']}")
                    logger.debug("capacity_report sent")
                else:
                    logger.warning(f"capacity_report failed: {resp.status_code}")
            
            # Log heartbeat / 记录心跳
            if self._report_count % 10 == 0:
                logger.info(f"Status report #{self._report_count} | user={self.config.user_id[:8]}...")
            
            return True
        
        except Exception as e:
            logger.error(f"Status report exception: {e}")
            return False
    
    def _prelock_ack(self, job_id: str) -> bool:
        """
        Send Pre-lock ACK
        发送 Pre-lock 确认
        """
        try:
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/jobs/{job_id}/prelock/ack",
                json={"node_id": self.config.node_id},
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "reserved":
                    return True
                else:
                    logger.warning(f"Pre-lock expired: {job_id[:12]}...")
                    return False
            else:
                return False
        
        except Exception as e:
            logger.error(f"Pre-lock ACK exception: {e}")
            return False
