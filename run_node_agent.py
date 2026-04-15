#!/usr/bin/env python3
"""
Node Agent - 连接 Render 上的 DCM
支持 Node_ID 持久化和无匹配自动注册
"""

import sys
import os
import time
import json
import hashlib
import base64
import requests
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
DCM_URL = "https://dcm-api-p00a.onrender.com"
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:7b"

# 持久化文件
NODE_ID_FILE = ".node_id"
NODE_INFO_FILE = ".node_info"

# 节点能力配置
NODE_CAPABILITY = {
    "user_id": "55de1671-1c55-4410-a078-a63922db9e8e",  # TODO: Replace with your user_id
    "address": "localhost",
    "port": 11434,
    "models": [MODEL],
    "bid_price": 0.001,
    "gpu_type": "NVIDIA RTX (Local)",
    "vram_gb": 24,
    "ask_price": 0.000001,  # USDC per token
    "avg_latency": 100,
    "avg_success_rate": 0.98,  # 98% 成功率
    "avg_quality_score": 0.95,  # 95% 质量评分
    "region": "local"
}

def load_node_id():
    """加载保存的 Node_ID"""
    if os.path.exists(NODE_ID_FILE):
        node_id = open(NODE_ID_FILE).read().strip()
        if node_id:
            return node_id
    return None

def save_node_id(node_id):
    """保存 Node_ID"""
    with open(NODE_ID_FILE, 'w') as f:
        f.write(node_id)
    logger.info(f"Node_ID 已保存: {node_id}")

def save_node_info(node_id):
    """保存节点信息"""
    with open(NODE_INFO_FILE, 'w') as f:
        json.dump({
            'node_id': node_id,
            'capability': NODE_CAPABILITY,
            'bound_at': datetime.utcnow().isoformat()
        }, f, indent=2)

class NodeAgent:
    def __init__(self):
        self.node_id = None
        self.ollama_url = OLLAMA_URL
        self.model = MODEL
        self.dcm_url = DCM_URL
        self.poll_interval = 3
        self.capability = NODE_CAPABILITY
        
    def register_new_node(self):
        """注册新节点"""
        logger.info("注册新节点...")
        
        try:
            resp = requests.post(f"{self.dcm_url}/api/v1/nodes", json=self.capability, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            self.node_id = result['node_id']
            save_node_id(self.node_id)
            save_node_info(self.node_id)
            
            logger.info(f"新节点注册成功: {self.node_id}")
            return True
        except Exception as e:
            logger.error(f"节点注册失败: {e}")
            return False
    
    def check_and_register_if_needed(self):
        """检查节点状态，必要时重新注册"""
        if not self.node_id:
            self.node_id = load_node_id()
        
        if not self.node_id:
            # 首次注册
            return self.register_new_node()
        
        # 检查节点是否存在
        try:
            resp = requests.get(f"{self.dcm_url}/api/v1/nodes/{self.node_id}", timeout=5)
            if resp.status_code != 200:
                logger.warning(f"节点 {self.node_id} 不存在，重新注册")
                return self.register_new_node()
            
            logger.info(f"使用已存在的节点: {self.node_id}")
            return True
        except:
            logger.warning(f"无法获取节点 {self.node_id}，重新注册")
            return self.register_new_node()
    
    def ensure_online(self):
        """确保节点在线"""
        try:
            resp = requests.get(f"{self.dcm_url}/api/v1/nodes/{self.node_id}", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            
            if status in ("offline", "active"):
                # 充值（如果需要）
                stake_required = data.get("stake_required", 200)
                if data.get("stake_amount", 0) < stake_required or stake_required == 0:
                    try:
                        requests.post(
                            f"{self.dcm_url}/api/v1/nodes/{self.node_id}/stake/deposit",
                            json={"amount": stake_required or 200},
                            timeout=10
                        )
                        logger.info(f"Stake 充值成功: {stake_required or 200}")
                    except Exception as e:
                        if "already deposited" in str(e):
                            logger.info("Stake 已存在，跳过")
                        else:
                            raise
                
                # 上线
                resp = requests.post(f"{self.dcm_url}/api/v1/nodes/{self.node_id}/online", timeout=10)
                resp.raise_for_status()
                logger.info("节点已上线")
            elif status == "online":
                logger.info("节点已在线")
                
        except Exception as e:
            logger.error(f"上线失败: {e}")
    
    def heartbeat(self):
        """发送 live_status (每 3 秒)"""
        try:
            resp = requests.post(
                f"{self.dcm_url}/api/v1/nodes/{self.node_id}/live_status",
                json={
                    "timestamp": int(time.time() * 1000),
                    "status": {
                        "status": "online",
                    },
                    "capacity": {
                        "max_concurrency_total": 2,
                        "max_concurrency_available": 2,
                    },
                    "load": {
                        "active_jobs": 0,
                        "available_token_capacity": 100000,
                    }
                },
                timeout=5
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"live_status 失败: {e}")
            return False
    
    def send_capacity_report(self):
        """发送 capacity_report (每 90 秒)"""
        try:
            resp = requests.post(
                f"{self.dcm_url}/api/v1/nodes/{self.node_id}/capacity_report",
                json={
                    "timestamp": int(time.time() * 1000),
                    "runtime": {
                        "type": "ollama",
                        "loaded_models": [self.model],
                    },
                    "user_id": self.capability.get("user_id", ""),
                    "ask_price": self.capability.get("ask_price", 0.001),
                    "avg_latency": self.capability.get("avg_latency", 100),
                    "gpu_count": self.capability.get("gpu_count", 1),
                    "capacity": {
                        "max_concurrency_total": 2,
                    },
                },
                timeout=10
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("new_cluster_id"):
                    logger.info(f"Cluster ID: {result['new_cluster_id']}")
            logger.debug("capacity_report sent")
            return True
        except Exception as e:
            logger.warning(f"capacity_report 失败: {e}")
            return False
    
    def poll_job(self):
        """轮询 Job - 返回完整的 invoke 结构"""
        try:
            resp = requests.post(f"{self.dcm_url}/api/v1/nodes/{self.node_id}/poll", timeout=10)
            
            if resp.status_code == 404:
                # 节点不存在，重新注册
                logger.warning(f"节点 {self.node_id} 不存在，重新注册")
                if self.register_new_node():
                    self.ensure_online()
                return None
            
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("has_job"):
                # 返回完整的 invoke 结构
                return {
                    "execution_id": result.get("execution_id"),
                    "job_id": result.get("job_id"),
                    "slot_id": result.get("slot_id"),
                    "model": result.get("model", {}),
                    "input": result.get("input", {}),
                    "generation": result.get("generation", {}),
                    "runtime": result.get("runtime", {}),
                    "locked_price": result.get("locked_price"),
                }
            
            return None
        except:
            return None
    
    def call_ollama(self, prompt: str, timeout: int = 120, model: str = None) -> tuple:
        """调用 Ollama 推理
        
        Args:
            prompt: 输入提示
            timeout: 超时时间
            model: 可选，指定模型（用于通用任务）
        """
        start_time = time.time()
        use_model = model or self.model
        payload = {
            "model": use_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 50}  # 简短回答
        }
        
        try:
            resp = requests.post(f"{self.ollama_url}/api/generate", json=payload, timeout=timeout)
            resp.raise_for_status()
            result = resp.json()
            latency_ms = int((time.time() - start_time) * 1000)
            output_tokens = len(result.get("response", "").split())
            return result.get("response", ""), latency_ms, output_tokens
        except Exception as e:
            logger.error(f"Ollama 调用失败: {e}")
            return None, 0, 0
    
    def submit_result(self, job_id: str, result: str, latency_ms: int, output_tokens: int):
        """提交结果"""
        # Base64 编码结果
        encoded_result = base64.b64encode(result.encode()).decode()
        result_hash = hashlib.sha256(result.encode()).hexdigest()
        payload = {
            "job_id": job_id,
            "result": encoded_result,
            "result_hash": result_hash,
            "actual_latency_ms": latency_ms,
            "actual_output_tokens": output_tokens
        }
        
        try:
            resp = requests.post(
                f"{self.dcm_url}/api/v1/nodes/{self.node_id}/jobs/{job_id}/result",
                json=payload, timeout=30
            )
            resp.raise_for_status()
            result_data = resp.json()
            layer = result_data.get("layer", 1)
            logger.info(f"✓ 结果提交成功 (Layer {layer})")
            return True
        except Exception as e:
            logger.error(f"结果提交失败: {e}")
            return False
    
    def run(self):
        """运行 Agent"""
        logger.info("=" * 50)
        logger.info("Node Agent 启动")
        logger.info(f"DCM: {self.dcm_url}")
        logger.info(f"Model: {self.model}")
        logger.info("=" * 50)
        
        # 检查并注册节点
        if not self.check_and_register_if_needed():
            logger.error("注册失败，退出")
            return
        
        # 确保上线
        self.ensure_online()
        
        heartbeat_count = 0
        capacity_count = 0
        processed_jobs = set()
        
        while True:
            try:
                # live_status (每 3 秒)
                heartbeat_count += 1
                if heartbeat_count % 10 == 0:
                    self.heartbeat()
                    heartbeat_count = 0
                
                # capacity_report (每 90 秒，约 30 次心跳)
                capacity_count += 1
                if capacity_count % 30 == 0:
                    self.send_capacity_report()
                
                # 轮询 Job
                invoke = self.poll_job()
                if invoke and invoke["job_id"] not in processed_jobs:
                    job_id = invoke["job_id"]
                    execution_id = invoke.get("execution_id")
                    processed_jobs.add(job_id)
                    
                    # 从 invoke 结构中提取信息
                    model_info = invoke.get("model", {})
                    used_model = model_info.get("name", self.model)
                    
                    # 从 input.messages 中提取 prompt
                    input_data = invoke.get("input", {})
                    messages = input_data.get("messages", [])
                    prompt = None
                    for msg in messages:
                        if msg.get("role") == "user":
                            prompt = msg.get("content", "Hello")
                            break
                    if not prompt:
                        prompt = "Hello"
                    
                    generation = invoke.get("generation", {})
                    max_tokens = generation.get("max_tokens", 100)
                    
                    logger.info(f"📥 收到 Job: {job_id[:8]}... (exec: {execution_id[:8] if execution_id else 'N/A'}..., model: {used_model}, prompt: {prompt[:30]}...)")
                    
                    # 调用 Ollama 执行推理
                    response, latency, tokens = self.call_ollama(prompt, model=used_model, max_tokens=max_tokens)
                    
                    if response:
                        logger.info(f"⚙️ 推理完成: {latency}ms, {tokens} tokens")
                        self.submit_result(job_id, response[:500], latency, tokens)
                    else:
                        logger.error(f"推理失败: {job_id[:8]}...")
                
                time.sleep(self.poll_interval)
                
            except KeyboardInterrupt:
                logger.info("退出")
                break
            except Exception as e:
                logger.error(f"错误: {e}")
                time.sleep(5)


if __name__ == "__main__":
    agent = NodeAgent()
    agent.run()
