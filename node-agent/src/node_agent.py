"""
DCM Node Agent - 核心模块

功能：注册/心跳/接Job/处理并返回结果
基于 F16-Runtime-Adapter-Layer 架构
支持多网络协议: HTTPS, P2P, Relay
"""

import os
import json
import time
import uuid
import logging
import threading
import hashlib
import base64
from dataclasses import dataclass
from typing import Optional, Dict, Set
from pathlib import Path
import requests

from .runtime_adapter import RuntimeAdapter, create_runtime_adapter, ExecutionResult
from .network import (
    NetworkAdapter, NetworkConfig, NetworkType, NetworkState,
    Invoke, Result
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class NodeConfig:
    """节点配置"""
    dcm_url: str = "https://dcm-api-p00a.onrender.com"
    node_id: Optional[str] = None
    model: str = "qwen2.5:7b"
    gpu_count: int = 1
    slot_count: int = 4
    worker_count: int = 2
    poll_interval: int = 3
    heartbeat_interval: int = 30
    stake_amount: float = 200.0
    
    # 网络配置
    network_enabled: bool = True
    p2p_enabled: bool = False
    relay_enabled: bool = False
    
    @classmethod
    def from_file(cls, path: str = ".node_agent_id") -> "NodeConfig":
        """从文件加载配置"""
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
                return cls(**data)
        return cls()
    
    def save(self, path: str = ".node_agent_id"):
        """保存配置到文件"""
        with open(path, 'w') as f:
            json.dump({
                "node_id": self.node_id,
                "model": self.model,
                "gpu_count": self.gpu_count,
                "slot_count": self.slot_count,
                "worker_count": self.worker_count,
                "dcm_url": self.dcm_url,
            }, f)


class DCMNodeAgent:
    """DCM Node Agent - 边缘执行节点
    
    支持多网络协议:
    - HTTPS: 标准轮询
    - P2P: 点对点通信 (gossipsub)
    - Relay: 中继穿透
    """
    
    def __init__(self, config: Optional[NodeConfig] = None):
        self.config = config or NodeConfig()
        
        # 网络适配器
        self.network = NetworkAdapter(NetworkConfig(
            primary=NetworkType.HTTPS,
            https_endpoint=self.config.dcm_url,
            fallback_enabled=True,
        ))
        
        # Runtime 适配器
        self.runtime = create_runtime_adapter({
            "backend": "ollama",
            "base_url": "http://localhost:11434"
        })
        
        # 状态
        self.processed_jobs: Set[str] = set()
        self.running = False
        self.lock = threading.Lock()
        
        # 网络状态监控
        self._setup_network_callbacks()
        
        # 确保节点 ID 持久化
        self._ensure_node_id()
    
    def _setup_network_callbacks(self):
        """设置网络回调"""
        def on_network_change(state: NetworkState, data: any):
            logger.info(f"网络状态变化: {state.value}")
        
        self.network.register_callback("state_change", on_network_change)
    
    def _ensure_node_id(self):
        """确保节点 ID 存在"""
        if not self.config.node_id:
            config = NodeConfig.from_file()
            if config.node_id:
                self.config.node_id = config.node_id
                logger.info(f"恢复节点 ID: {self.config.node_id}")
    
    # ==================== 注册相关 ====================
    
    def check_node_exists(self) -> bool:
        """检查节点是否已存在"""
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
        """注册新节点"""
        try:
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes",
                json={
                    "gpu_type": "Apple Silicon",
                    "vram_gb": 36,
                    "model_support": [self.config.model],
                    "ask_price": 0.001,
                    "avg_latency": 200,
                    "region": "local",
                    "gpu_count": self.config.gpu_count,
                },
                timeout=30
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.config.node_id = data["node_id"]
                self.config.save()
                logger.info(f"✅ 节点注册成功: {self.config.node_id}")
                return True
            else:
                logger.error(f"注册失败: {resp.status_code} - {resp.text}")
                return False
                
        except Exception as e:
            logger.error(f"注册异常: {e}")
            return False
    
    def ensure_online(self) -> bool:
        """确保节点在线"""
        # 连接网络
        if not self.network.connect():
            logger.warning("网络连接失败")
        
        # 检查节点是否存在
        if not self.check_node_exists():
            if not self.register_node():
                return False
        
        # 激活节点为 ONLINE
        if not self.activate_online():
            logger.warning("节点激活失败")
        
        return self.heartbeat()
    
    def activate_online(self) -> bool:
        """激活节点为 ONLINE 状态"""
        if not self.config.node_id:
            return False
        
        try:
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}/online",
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"✅ 节点激活: {data.get('status', 'online')}")
                return True
            else:
                logger.warning(f"激活失败: {resp.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"激活异常: {e}")
            return False
    
    def heartbeat(self) -> bool:
        """发送心跳"""
        if not self.config.node_id:
            return False
        
        try:
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}/heartbeat",
                json={"status": "idle"},
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("matched"):
                    logger.debug("节点已匹配")
                
                # 更新网络状态
                self.network.current_state = NetworkState.ONLINE
                return True
            else:
                logger.warning(f"心跳失败: {resp.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"心跳异常: {e}")
            return False
    
    # ==================== Job 处理 ====================
    
    def poll_job(self) -> Optional[Invoke]:
        """轮询 Job - 返回 Invoke 结构
        
        支持多网络协议:
        - HTTPS: 标准 REST API
        - P2P: 点对点推送 (预留)
        - Relay: 中继推送 (预留)
        """
        if not self.config.node_id:
            return None
        
        try:
            # HTTPS 轮询
            if self.network.current_type in [NetworkType.HTTPS, NetworkType.WSS]:
                return self._poll_job_https()
            
            # P2P 轮询 (预留)
            elif self.network.current_type == NetworkType.P2P:
                return self._poll_job_p2p()
            
            # Relay 轮询 (预留)
            elif self.network.current_type == NetworkType.RELAY:
                return self._poll_job_relay()
            
            return None
            
        except Exception as e:
            logger.error(f"轮询 Job 异常: {e}")
            return None
    
    def _poll_job_https(self) -> Optional[Invoke]:
        """HTTPS 轮询"""
        try:
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}/poll",
                timeout=10
            )
            
            if resp.status_code == 404:
                logger.warning("节点不存在，重新注册")
                if self.register_node():
                    self.ensure_online()
                return None
            
            if resp.status_code != 200:
                return None
            
            result = resp.json()
            
            if not result.get("has_job"):
                return None
            
            # 构建 Invoke
            invoke = Invoke(result)
            invoke.network_type = NetworkType.HTTPS
            
            return invoke
            
        except Exception as e:
            logger.error(f"HTTPS 轮询异常: {e}")
            return None
    
    def _poll_job_p2p(self) -> Optional[Invoke]:
        """P2P 轮询 (预留)"""
        # TODO: 实现 P2P 消息订阅
        logger.debug("P2P 轮询模式")
        
        # 暂时降级到 HTTPS
        self.network.current_type = NetworkType.HTTPS
        return self._poll_job_https()
    
    def _poll_job_relay(self) -> Optional[Invoke]:
        """Relay 轮询 (预留)"""
        # TODO: 实现 Relay 消息订阅
        logger.debug("Relay 轮询模式")
        
        # 暂时降级到 HTTPS
        self.network.current_type = NetworkType.HTTPS
        return self._poll_job_https()
    
    def submit_result(
        self,
        job_id: str,
        result_text: str,
        latency_ms: int,
        output_tokens: int,
        network_type: Optional[NetworkType] = None
    ) -> bool:
        """提交执行结果
        
        支持多网络返回:
        - HTTPS: REST API
        - P2P: 点对点传输 (预留)
        - Relay: 中继传输 (预留)
        """
        if not self.config.node_id:
            return False
        
        network_type = network_type or self.network.current_type
        
        try:
            # Base64 编码结果
            encoded_result = base64.b64encode(result_text.encode()).decode()
            result_hash = hashlib.sha256(result_text.encode()).hexdigest()
            
            payload = {
                "job_id": job_id,
                "result": encoded_result,
                "result_hash": result_hash,
                "actual_latency_ms": latency_ms,
                "actual_output_tokens": output_tokens,
                "network_type": network_type.value,
            }
            
            # 根据网络类型选择提交方式
            if network_type == NetworkType.HTTPS:
                return self._submit_result_https(job_id, payload)
            else:
                # 其他网络类型暂时降级到 HTTPS
                return self._submit_result_https(job_id, payload)
            
        except Exception as e:
            logger.error(f"提交结果异常: {e}")
            return False
    
    def _submit_result_https(self, job_id: str, payload: Dict) -> bool:
        """HTTPS 提交结果"""
        try:
            resp = requests.post(
                f"{self.config.dcm_url}/api/v1/nodes/{self.config.node_id}/jobs/{job_id}/result",
                json=payload,
                timeout=30
            )
            
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"✅ 结果提交成功 (Layer {data.get('layer', 1)})")
                return True
            else:
                logger.error(f"结果提交失败: {resp.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"HTTPS 提交失败: {e}")
            return False
    
    def process_job(self, invoke: Invoke) -> bool:
        """处理单个 Job"""
        job_id = invoke.job_id
        
        if not job_id:
            return False
        
        # 提取 prompt
        prompt = invoke.get_prompt() or "Hello"
        
        # 获取模型
        model_name = invoke.get_model_name()
        
        # 获取生成参数
        max_tokens = invoke.get_max_tokens()
        
        logger.info(f"📥 处理 Job: {job_id[:8]}... | network: {invoke.network_type.value} | model: {model_name} | prompt: {prompt[:30]}...")
        
        # 构建 runtime invoke
        runtime_invoke = invoke.to_dict()
        runtime_invoke["generation"]["max_tokens"] = max_tokens
        
        # 调用 Runtime 执行推理
        result = self.runtime.execute(runtime_invoke)
        
        if result.status == "completed":
            output_text = result.output.get("text", "")
            latency = result.metrics.get("latency_ms", 0)
            tokens = result.usage.get("output_tokens", 0)
            
            logger.info(f"✅ 推理完成: {latency}ms, {tokens} tokens")
            
            # 提交结果
            return self.submit_result(job_id, output_text, latency, tokens, invoke.network_type)
        else:
            logger.error(f"❌ 推理失败: {result.error}")
            return False
    
    # ==================== 主循环 ====================
    
    def run(self):
        """运行 Agent 主循环"""
        logger.info("=" * 50)
        logger.info("DCM Node Agent 启动")
        logger.info(f"DCM: {self.config.dcm_url}")
        logger.info(f"Model: {self.config.model}")
        logger.info(f"Network: {self.network.current_type.value}")
        logger.info("=" * 50)
        
        # 确保节点在线
        if not self.check_node_exists():
            if not self.register_node():
                logger.error("节点注册失败，退出")
                return
        
        if not self.ensure_online():
            logger.error("节点上线失败，退出")
            return
        
        self.running = True
        heartbeat_count = 0
        
        logger.info("✅ 节点已上线，开始处理 Job")
        
        while self.running:
            try:
                # 心跳
                heartbeat_count += 1
                if heartbeat_count % (self.config.heartbeat_interval // self.config.poll_interval) == 0:
                    self.heartbeat()
                
                # 轮询 Job
                invoke = self.poll_job()
                
                if invoke:
                    job_id = invoke.job_id
                    
                    with self.lock:
                        if job_id not in self.processed_jobs:
                            self.processed_jobs.add(job_id)
                            
                            # 处理 Job
                            self.process_job(invoke)
                            
                            # 清理已处理的 Job（防止内存泄漏）
                            if len(self.processed_jobs) > 1000:
                                self.processed_jobs = set(list(self.processed_jobs)[-500:])
                
                time.sleep(self.config.poll_interval)
                
            except KeyboardInterrupt:
                logger.info("收到退出信号")
                break
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                time.sleep(5)
        
        logger.info("Agent 已停止")
    
    def stop(self):
        """停止 Agent"""
        self.running = False
        self.network.disconnect()


def main():
    """入口函数"""
    agent = DCMNodeAgent()
    agent.run()


if __name__ == "__main__":
    main()
