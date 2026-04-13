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
    "address": "localhost",
    "port": 11434,
    "models": [MODEL],
    "bid_price": 0.001,
    "gpu_type": "NVIDIA RTX (Local)",
    "vram_gb": 24,
    "ask_price": 0.002,
    "avg_latency": 100,
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
                # 充值
                stake_required = data.get("stake_required", 200)
                if data.get("stake_amount", 0) < stake_required:
                    requests.post(
                        f"{self.dcm_url}/api/v1/nodes/{self.node_id}/stake/deposit",
                        json={"amount": stake_required},
                        timeout=10
                    )
                    logger.info(f"Stake 充值成功: {stake_required}")
                
                # 上线
                resp = requests.post(f"{self.dcm_url}/api/v1/nodes/{self.node_id}/online", timeout=10)
                resp.raise_for_status()
                logger.info("节点已上线")
            elif status == "online":
                logger.info("节点已在线")
                
        except Exception as e:
            logger.error(f"上线失败: {e}")
    
    def heartbeat(self):
        """发送心跳并处理 re_register"""
        try:
            resp = requests.post(
                f"{self.dcm_url}/api/v1/nodes/{self.node_id}/heartbeat",
                json={"status": "online", "current_jobs": 0},
                timeout=5
            )
            
            if resp.status_code == 200:
                result = resp.json()
                
                # 检查是否需要重新注册
                if result.get("re_register"):
                    logger.warning("服务端要求重新注册节点")
                    if self.register_new_node():
                        self.ensure_online()
                
                # 检查是否匹配成功
                if not result.get("matched"):
                    logger.debug("节点未在 matching_service 中")
                
                return result
            return None
        except:
            return None
    
    def poll_job(self):
        """轮询 Job"""
        try:
            resp = requests.post(f"{self.dcm_url}/api/v1/nodes/{self.node_id}/poll", timeout=10)
            resp.raise_for_status()
            result = resp.json()
            return result.get("job") if result.get("has_job") else None
        except:
            return None
    
    def call_ollama(self, prompt: str, timeout: int = 120) -> tuple:
        """调用 Ollama 推理"""
        start_time = time.time()
        payload = {
            "model": self.model,
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
        result_hash = hashlib.sha256(result.encode()).hexdigest()
        payload = {
            "job_id": job_id,
            "result": result,
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
        processed_jobs = set()
        
        while True:
            try:
                # 心跳
                heartbeat_count += 1
                if heartbeat_count % 10 == 0:
                    self.heartbeat()
                    heartbeat_count = 0
                
                # 轮询 Job
                job = self.poll_job()
                if job and job["job_id"] not in processed_jobs:
                    job_id = job["job_id"]
                    processed_jobs.add(job_id)
                    
                    logger.info(f"📥 收到 Job: {job_id[:8]}...")
                    response, latency, tokens = self.call_ollama("你好")
                    
                    if response:
                        logger.info(f"⚙️ 推理完成: {latency}ms, {tokens} tokens")
                        self.submit_result(job_id, response[:500], latency, tokens)
                
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
