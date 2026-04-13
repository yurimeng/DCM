#!/usr/bin/env python3
"""
Node Agent - 连接 Render 上的 DCM
使用已有节点，不重复注册
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

# 配置 - 使用已有的节点 ID
DCM_URL = "https://dcm-api-p00a.onrender.com"
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:7b"
NODE_ID = "14bede16-a406-42bf-8775-4b19f164ef16"  # 使用已有的节点

class NodeAgent:
    def __init__(self):
        self.node_id = NODE_ID
        self.ollama_url = OLLAMA_URL
        self.model = MODEL
        self.dcm_url = DCM_URL
        self.poll_interval = 3  # 秒
        self.registered = True  # 节点已注册
        
    def ensure_online(self):
        """确保节点在线"""
        # 检查当前状态
        try:
            resp = requests.get(f"{self.dcm_url}/api/v1/nodes/{self.node_id}", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            
            if status == "offline":
                # 需要上线
                if data.get("stake_amount", 0) < data.get("stake_required", 200):
                    # 充值
                    requests.post(
                        f"{self.dcm_url}/api/v1/nodes/{self.node_id}/stake/deposit",
                        json={"amount": 200.0},
                        timeout=10
                    )
                
                # 上线
                requests.post(f"{self.dcm_url}/api/v1/nodes/{self.node_id}/online", timeout=10)
                logger.info("节点已上线")
            elif status == "online":
                logger.info("节点已在线")
            else:
                logger.info(f"节点状态: {status}")
                
        except Exception as e:
            logger.error(f"检查/上线失败: {e}")
    
    def heartbeat(self):
        """发送心跳"""
        try:
            resp = requests.post(
                f"{self.dcm_url}/api/v1/nodes/{self.node_id}/heartbeat",
                json={"status": "online", "current_jobs": 0},
                timeout=5
            )
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"心跳失败: {e}")
            return False
    
    def poll_job(self):
        """轮询 Job"""
        try:
            resp = requests.post(f"{self.dcm_url}/api/v1/nodes/{self.node_id}/poll", timeout=10)
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("has_job"):
                return result["job"]
            return None
        except Exception as e:
            logger.debug(f"轮询失败: {e}")
            return None
    
    def call_ollama(self, prompt: str, timeout: int = 120) -> tuple:
        """调用 Ollama 推理"""
        start_time = time.time()
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": 500  # 限制输出
            }
        }
        
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=timeout
            )
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
        # 计算哈希
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
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
            result_data = resp.json()
            logger.info(f"结果提交成功: {result_data}")
            return True
        except Exception as e:
            logger.error(f"结果提交失败: {e}")
            return False
    
    def run(self):
        """运行 Agent"""
        logger.info("=" * 50)
        logger.info("Node Agent 启动")
        logger.info(f"DCM: {self.dcm_url}")
        logger.info(f"Ollama: {self.ollama_url}")
        logger.info(f"Model: {self.model}")
        logger.info(f"Node ID: {self.node_id}")
        logger.info("=" * 50)
        
        # 确保节点在线
        self.ensure_online()
        
        heartbeat_count = 0
        
        # 主循环
        while True:
            try:
                # 发送心跳
                heartbeat_count += 1
                if heartbeat_count % 10 == 0:  # 每 10 次轮询发送一次心跳
                    self.heartbeat()
                    heartbeat_count = 0
                
                # 轮询 Job
                job = self.poll_job()
                
                if job:
                    logger.info(f"收到 Job: {job['job_id']}")
                    logger.info(f"  Model: {job['model']}")
                    logger.info(f"  Max Latency: {job['max_latency']}ms")
                    
                    # 构造 prompt
                    prompt = f"用户请求: {job.get('input_text', '请回答以下问题')}\n\n"
                    
                    # 调用 Ollama
                    logger.info("调用 Ollama 推理...")
                    response, latency, tokens = self.call_ollama(prompt)
                    
                    if response:
                        logger.info(f"推理完成: {latency}ms, {tokens} tokens")
                        # 截断响应
                        response = response[:2000]
                        
                        # 提交结果
                        self.submit_result(job["job_id"], response, latency, tokens)
                    else:
                        logger.error("推理失败，提交错误")
                
                # 等待
                time.sleep(self.poll_interval)
                
            except KeyboardInterrupt:
                logger.info("收到中断信号，退出")
                break
            except Exception as e:
                logger.error(f"主循环错误: {e}")
                time.sleep(5)


if __name__ == "__main__":
    agent = NodeAgent()
    agent.run()
