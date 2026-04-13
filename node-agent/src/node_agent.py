"""
DCM Node Agent - 核心模块

功能:注册/心跳/接Job/处理并返回结果
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
                # 调试日志
                import logging
                logging.getLogger(__name__).debug(f"加载配置: {data}")
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
                "p2p_enabled": self.p2p_enabled,
                "relay_enabled": self.relay_enabled,
            }, f)


class DCMNodeAgent:
    """DCM Node Agent - 边缘执行节点
    
    支持多网络协议:
    - HTTPS: 标准轮询
    - QUIC: HTTP/3 低延迟
    - P2P: 点对点通信 (gossipsub)
    - Relay: 中继穿透 (NAT 穿透)
    
    Prompt 下发: P2P/Relay/QUIC (优先)
    Job/结算: HTTPS
    """
    
    def __init__(self, config: Optional[NodeConfig] = None):
        self.config = config or NodeConfig.from_file()
        
        # 确定首选网络类型
        primary_network = NetworkType.HTTPS
        if self.config.relay_enabled:
            primary_network = NetworkType.RELAY
        elif self.config.p2p_enabled:
            primary_network = NetworkType.P2P
        
        # 保存首选网络 (用于日志)
        self._preferred_network = primary_network
        
        # 网络适配器
        self.network = NetworkAdapter(NetworkConfig(
            primary=primary_network,
            https_endpoint=self.config.dcm_url,
            fallback_enabled=True,
            relay_enabled=self.config.relay_enabled,
            quic_enabled=True,
        ))
        
        # 记录原始请求的网络类型 (用于日志)
        self._requested_network: Optional[NetworkType] = None

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

    def ensure_online(self, max_retries: int = -1) -> bool:
        """确保节点在线
        
        Args:
            max_retries: 最大重试次数，-1 表示无限重试
            
        如果无法连接，会每 30 秒重试一次，直到成功或达到最大重试次数
        """
        retry_count = 0
        retry_interval = 30  # 30 秒重试一次
        
        while True:
            retry_count += 1
            
            # 尝试连接网络
            if not self.network.connect():
                if max_retries > 0 and retry_count >= max_retries:
                    logger.error(f"网络连接失败，已重试 {retry_count} 次，退出")
                    return False
                logger.warning(f"网络连接失败，{retry_interval} 秒后重试... ({retry_count})")
                time.sleep(retry_interval)
                continue

            # 检查节点是否存在
            if not self.check_node_exists():
                if not self.register_node():
                    if max_retries > 0 and retry_count >= max_retries:
                        logger.error(f"节点注册失败，已重试 {retry_count} 次，退出")
                        return False
                    logger.warning(f"节点注册失败，{retry_interval} 秒后重试... ({retry_count})")
                    time.sleep(retry_interval)
                    continue

            # 激活节点为 ONLINE
            if not self.activate_online():
                logger.warning("节点激活失败")
                # 激活失败不重试，继续尝试心跳

            # 心跳检查
            if self.heartbeat():
                logger.info(f"✅ 节点在线 ({retry_count} 次尝试)")
                return True
            
            if max_retries > 0 and retry_count >= max_retries:
                logger.error(f"心跳失败，已重试 {retry_count} 次，退出")
                return False
            
            logger.warning(f"心跳失败，{retry_interval} 秒后重试... ({retry_count})")
            time.sleep(retry_interval)

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

        网络优先级:
        - QUIC: HTTP/3 (低延迟)
        - Relay: 中继穿透
        - P2P: 点对点
        - HTTPS: 降级 fallback

        Prompt 通过首选协议下发，Job/结算走 HTTPS
        """
        if not self.config.node_id:
            return None

        try:
            # 记录原始请求的网络类型
            original_type = self.network.current_type
            
            # 根据网络类型选择轮询方式
            if original_type == NetworkType.QUIC:
                return self._poll_job_quic()
            elif original_type == NetworkType.RELAY:
                return self._poll_job_relay()
            elif original_type == NetworkType.P2P:
                return self._poll_job_p2p()
            else:
                # HTTPS 或其他
                return self._poll_job_https()

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
                logger.warning("节点不存在,重新注册")
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

    def _poll_job_quic(self) -> Optional[Invoke]:
        """QUIC 轮询

        通过 QUIC/HTTP3 协议拉取 Job
        优点: 低延迟, 0-RTT 恢复, 连接迁移
        """
        try:
            # 使用网络适配器的 QUIC 连接
            result = self.network.post(
                f"/api/v1/nodes/{self.config.node_id}/poll",
                {}
            )

            if not result:
                # QUIC 失败,降级到 HTTPS
                logger.warning("QUIC 轮询失败,降级到 HTTPS")
                self.network.switch_to_https()
                return self._poll_job_https()

            if not result.get("has_job"):
                return None

            # 构建 Invoke
            invoke = Invoke(result)
            invoke.network_type = NetworkType.QUIC

            logger.info(f"📥 QUIC 拉取 Job: {invoke.job_id[:8]}...")
            return invoke

        except Exception as e:
            logger.error(f"QUIC 轮询异常: {e}")
            # 降级到 HTTPS
            self.network.switch_to_https()
            return self._poll_job_https()

    def _poll_job_p2p(self) -> Optional[Invoke]:
        """P2P 轮询

        通过 libp2p gossipsub 订阅 Job 消息
        优点: 无需轮询, 实时推送, 去中心化
        """
        try:
            # 获取 Relay 地址
            relay_addr = self.network.get_relay_addr()

            if relay_addr:
                logger.info(f"🔗 P2P 模式,使用 Relay: {relay_addr}")
            else:
                logger.warning("Relay 未连接,P2P 不可用")
                # 降级到 HTTPS
                self.network.current_type = NetworkType.HTTPS
                return self._poll_job_https()

            # TODO: 实现 gossipsub 消息订阅
            # 这里暂时使用 HTTPS 作为后备
            return self._poll_job_https()

        except Exception as e:
            logger.error(f"P2P 轮询异常: {e}")
            self.network.current_type = NetworkType.HTTPS
            return self._poll_job_https()

    def _poll_job_relay(self) -> Optional[Invoke]:
        """Relay 轮询

        通过 circuit relay 中继拉取 Job
        用于 NAT 穿透场景
        """
        try:
            relay_addr = self.network.get_relay_addr()

            if relay_addr:
                logger.info(f"🔄 通过 Relay 拉取: {relay_addr}")

            # 使用网络适配器发送 Relay 请求
            result = self.network.request(
                "POST",
                f"/api/v1/nodes/{self.config.node_id}/poll",
                {}
            )

            if not result:
                logger.warning("Relay 请求失败,降级到 HTTPS")
                self.network.current_type = NetworkType.HTTPS
                return self._poll_job_https()

            if not result.get("has_job"):
                return None

            # 构建 Invoke
            invoke = Invoke(result)
            invoke.network_type = NetworkType.RELAY

            return invoke

        except Exception as e:
            logger.error(f"Relay 轮询异常: {e}")
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

        注意: Job 提交和结算强制走 HTTPS
        只有 Prompt 可以通过 QUIC/Relay/P2P 获取
        """
        if not self.config.node_id:
            return False

        # 记录 prompt 获取时使用的网络类型
        prompt_network = network_type or self.network.current_type

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
                "prompt_network": prompt_network.value,  # 记录 prompt 来源
            }

            # Job 提交和结算强制走 HTTPS
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

    def _submit_result_quic(self, job_id: str, payload: Dict) -> bool:
        """QUIC 提交结果

        通过 QUIC/HTTP3 协议提交结果
        优点: 低延迟, 0-RTT 恢复
        """
        try:
            # 使用网络适配器的 QUIC 连接
            result = self.network.post(
                f"/api/v1/nodes/{self.config.node_id}/jobs/{job_id}/result",
                payload
            )

            if result and result.get("received"):
                logger.info(f"✅ QUIC 结果提交成功 (Layer {result.get('layer', 1)})")
                return True
            else:
                # QUIC 失败,降级到 HTTPS
                logger.warning("QUIC 提交失败,降级到 HTTPS")
                return self._submit_result_https(job_id, payload)

        except Exception as e:
            logger.error(f"QUIC 提交失败: {e}")
            return self._submit_result_https(job_id, payload)

    def _submit_result_relay(self, job_id: str, payload: Dict) -> bool:
        """Relay 提交结果

        通过 circuit relay 中继提交结果
        用于 NAT 穿透场景
        """
        try:
            # 使用网络适配器的 Relay 连接
            result = self.network.request(
                "POST",
                f"/api/v1/nodes/{self.config.node_id}/jobs/{job_id}/result",
                payload
            )

            if result and result.get("received"):
                logger.info(f"✅ Relay 结果提交成功 (Layer {result.get('layer', 1)})")
                return True
            else:
                logger.warning("Relay 提交失败,降级到 HTTPS")
                return self._submit_result_https(job_id, payload)

        except Exception as e:
            logger.error(f"Relay 提交失败: {e}")
            return self._submit_result_https(job_id, payload)

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
        
        # 获取网络类型
        network_type = invoke.network_type.value
        actual_network = self.network.current_type.value
        
        # 显示网络来源信息
        if network_type != actual_network:
            net_info = f"prompt:{network_type}→actual:{actual_network}"
        else:
            net_info = network_type
        
        logger.info(f"📥 处理 Job: {job_id[:8]}... [{net_info}] | {model_name} | prompt: {prompt[:20]}...")

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
        # 使用保存的首选网络
        preferred_network = self._preferred_network
        
        logger.info("=" * 50)
        logger.info("DCM Node Agent 启动")
        logger.info(f"DCM: {self.config.dcm_url}")
        logger.info(f"Model: {self.config.model}")
        logger.info(f"Prompt via: {preferred_network.value}")
        logger.info("=" * 50)

        # 确保节点在线 (无限重试)
        logger.info("正在连接服务器...")
        if not self.ensure_online(max_retries=-1):
            logger.error("无法连接服务器，Agent 退出")
            return

        self.running = True
        heartbeat_count = 0

        logger.info(f"✅ 节点已上线 | 网络: {self.network.current_type.value} | Prompt via: {preferred_network.value}")

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

                            # 清理已处理的 Job(防止内存泄漏)
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
