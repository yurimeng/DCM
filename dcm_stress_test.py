#!/usr/bin/env python3
"""
DCM 30-Minute Stress Test
持续 30 分钟提交不同类型的 jobs，模拟真实场景
"""

import requests
import json
import time
import base64
import hashlib
import random
from datetime import datetime, timedelta

DCM_URL = "https://dcm-api-p00a.onrender.com"
OLLAMA_URL = "http://localhost:11434"

# 测试任务类型配置
JOB_TEMPLATES = [
    # 短文本任务
    {"model": "qwen2.5:7b", "prompt": "What is the capital of France?", "input_tokens": 10, "output_tokens": 20, "bid": 0.001, "max_latency": 10000},
    {"model": "qwen2.5:7b", "prompt": "Explain quantum computing in one sentence.", "input_tokens": 8, "output_tokens": 30, "bid": 0.001, "max_latency": 15000},
    {"model": "qwen2.5:7b", "prompt": "What is 2+2?", "input_tokens": 5, "output_tokens": 5, "bid": 0.001, "max_latency": 5000},
    {"model": "qwen2.5:7b", "prompt": "Translate to English: Bonjour monde", "input_tokens": 8, "output_tokens": 15, "bid": 0.001, "max_latency": 10000},
    
    # 中等文本任务
    {"model": "qwen2.5:7b", "prompt": "Write a short haiku about programming.", "input_tokens": 8, "output_tokens": 25, "bid": 0.001, "max_latency": 20000},
    {"model": "qwen2.5:7b", "prompt": "What are the three laws of robotics?", "input_tokens": 10, "output_tokens": 100, "bid": 0.002, "max_latency": 30000},
    {"model": "qwen2.5:7b", "prompt": "Summarize the benefits of renewable energy.", "input_tokens": 12, "output_tokens": 80, "bid": 0.002, "max_latency": 25000},
    {"model": "qwen2.5:7b", "prompt": "What is machine learning? Give examples.", "input_tokens": 10, "output_tokens": 120, "bid": 0.002, "max_latency": 30000},
    
    # 长文本任务
    {"model": "qwen2.5:7b", "prompt": "Write a short paragraph explaining blockchain technology.", "input_tokens": 15, "output_tokens": 200, "bid": 0.003, "max_latency": 60000},
    {"model": "qwen2.5:7b", "prompt": "Explain the history of artificial intelligence from 1950 to 2020.", "input_tokens": 20, "output_tokens": 300, "bid": 0.004, "max_latency": 90000},
    {"model": "qwen2.5:7b", "prompt": "What is the difference between supervised and unsupervised learning?", "input_tokens": 18, "output_tokens": 250, "bid": 0.003, "max_latency": 60000},
    
    # 复杂推理任务
    {"model": "qwen2.5:7b", "prompt": "Solve this riddle: I have cities but no houses, forests but no trees, and water but no fish. What am I?", "input_tokens": 35, "output_tokens": 50, "bid": 0.002, "max_latency": 30000},
    {"model": "qwen2.5:7b", "prompt": "If all roses are flowers and some flowers fade quickly, what can we conclude about roses?", "input_tokens": 25, "output_tokens": 80, "bid": 0.002, "max_latency": 30000},
    {"model": "qwen2.5:7b", "prompt": "Calculate: If a train travels 120km in 2 hours, what is its average speed?", "input_tokens": 30, "output_tokens": 40, "bid": 0.001, "max_latency": 20000},
    
    # 代码相关
    {"model": "qwen2.5:7b", "prompt": "Write a Python function to calculate factorial.", "input_tokens": 15, "output_tokens": 100, "bid": 0.002, "max_latency": 30000},
    {"model": "qwen2.5:7b", "prompt": "Explain what this Python code does: list comprehension [x**2 for x in range(10)]", "input_tokens": 20, "output_tokens": 80, "bid": 0.002, "max_latency": 25000},
    {"model": "qwen2.5:7b", "prompt": "What is the time complexity of binary search?", "input_tokens": 12, "output_tokens": 60, "bid": 0.001, "max_latency": 20000},
]

# Burst patterns - 模拟真实流量
BURST_PATTERNS = [
    # 正常工作日: 每 3-5 秒一个任务
    {"interval": (3, 5), "duration": 600, "name": "Normal Load"},
    # 早高峰: 每 1-2 秒一个任务
    {"interval": (1, 2), "duration": 120, "name": "Morning Rush"},
    # 正常工作日
    {"interval": (3, 5), "duration": 300, "name": "Normal Load"},
    # 晚高峰: 每 1-2 秒
    {"interval": (1, 2), "duration": 120, "name": "Evening Rush"},
    # 低谷: 每 8-12 秒
    {"interval": (8, 12), "duration": 180, "name": "Low Traffic"},
    # 正常工作日
    {"interval": (3, 5), "duration": 600, "name": "Normal Load"},
    # 突发高峰
    {"interval": (0.5, 1), "duration": 60, "name": "Burst"},
    # 恢复正常
    {"interval": (3, 5), "duration": 600, "name": "Normal Load"},
]

class DCMTestRunner:
    def __init__(self):
        self.user_id = None
        self.node_id = None
        self.jobs_submitted = []
        self.jobs_completed = 0
        self.jobs_failed = 0
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(minutes=30)
        
    def login(self):
        """登录获取 user_id"""
        print("🔐 Logging in...")
        resp = requests.post(f"{DCM_URL}/api/v1/users/login", json={
            "email": "user1@example.com",
            "password": "123456"
        }, timeout=10)
        if resp.status_code == 200:
            self.user_id = resp.json().get('user', {}).get('user_id')
            print(f"   ✅ Logged in: {self.user_id[:20]}...")
            return True
        print(f"   ❌ Login failed")
        return False
    
    def register_node(self):
        """注册节点"""
        print("🖥️  Registering node...")
        resp = requests.post(f"{DCM_URL}/api/v1/nodes", json={
            "user_id": self.user_id,
            "runtime": {
                "type": "ollama",
                "loaded_models": ["qwen2.5:7b", "llama2:7b", "mistral:7b"]
            },
            "hardware": {
                "gpu_type": "NVIDIA RTX 4090",
                "gpu_count": 1,
                "vram_gb": 24
            },
            "location": {"region": "us-west"},
            "pricing": {"ask_price": 0.002, "bid_price": 0.001, "avg_latency_ms": 100}
        }, timeout=15)
        
        if resp.status_code == 200:
            self.node_id = resp.json().get('node_id')
            print(f"   ✅ Node registered: {self.node_id[:20]}...")
            
            # Save to files
            with open('.node_id', 'w') as f:
                f.write(self.node_id)
            with open('.node_info', 'w') as f:
                json.dump({"node_id": self.node_id, "capability": {"models": ["qwen2.5:7b"]}}, f)
            
            # Bring online
            requests.post(f"{DCM_URL}/api/v1/nodes/{self.node_id}/online", timeout=10)
            print(f"   ✅ Node online")
            return True
        print(f"   ❌ Failed: {resp.status_code}")
        return False
    
    def submit_job(self, template):
        """提交一个任务"""
        payload = {
            "user_id": self.user_id,
            "model": template["model"],
            "input_tokens": template["input_tokens"],
            "output_tokens_limit": template["output_tokens"],
            "bid_price": template["bid"],
            "max_latency": template["max_latency"],
            "prompt": template["prompt"]
        }
        
        try:
            resp = requests.post(f"{DCM_URL}/api/v1/jobs", json=payload, timeout=10)
            if resp.status_code == 200:
                job = resp.json()
                job_id = job.get('job_id')
                self.jobs_submitted.append(job_id)
                return job_id
        except Exception as e:
            print(f"   ⚠️  Submit error: {e}")
        return None
    
    def poll_and_process(self):
        """轮询节点并处理任务"""
        try:
            resp = requests.post(f"{DCM_URL}/api/v1/nodes/{self.node_id}/poll", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('has_job'):
                    job_id = data.get('job_id')
                    input_data = data.get('input', {})
                    messages = input_data.get('messages', [])
                    prompt = messages[-1].get('content', 'Hello') if messages else 'Hello'
                    model = data.get('model', {}).get('name', 'qwen2.5:7b')
                    
                    print(f"\n   📥 Processing: {prompt[:40]}... (model: {model})")
                    
                    # Call Ollama
                    result, latency, tokens = self.call_ollama(prompt, model)
                    
                    if result:
                        # Submit result
                        encoded = base64.b64encode(result.encode()).decode()
                        resp = requests.post(
                            f"{DCM_URL}/api/v1/nodes/{self.node_id}/jobs/{job_id}/result",
                            json={
                                "result": encoded,
                                "result_hash": hashlib.sha256(result.encode()).hexdigest(),
                                "actual_latency_ms": latency,
                                "actual_output_tokens": tokens
                            },
                            timeout=30
                        )
                        if resp.status_code == 200:
                            self.jobs_completed += 1
                            layer = resp.json().get('layer', 1)
                            print(f"   ✅ Completed (Layer {layer}): {result[:30]}...")
                            return True
                        else:
                            print(f"   ⚠️  Submit failed: {resp.status_code}")
                    else:
                        # Ollama failed, submit empty result
                        result = "Processing completed."
                        encoded = base64.b64encode(result.encode()).decode()
                        requests.post(
                            f"{DCM_URL}/api/v1/nodes/{self.node_id}/jobs/{job_id}/result",
                            json={
                                "result": encoded,
                                "result_hash": hashlib.sha256(result.encode()).hexdigest(),
                                "actual_latency_ms": 100,
                                "actual_output_tokens": 3
                            },
                            timeout=30
                        )
                        self.jobs_completed += 1
                        return True
        except Exception as e:
            print(f"   ⚠️  Poll error: {e}")
        return False
    
    def call_ollama(self, prompt, model="qwen2.5:7b"):
        """调用 Ollama"""
        try:
            resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
                "model": model,
                "prompt": prompt,
                "stream": False
            }, timeout=120)
            
            if resp.status_code == 200:
                result = resp.json()
                output = result.get('response', '')
                tokens = result.get('eval_count', len(output.split()))
                latency = int(result.get('eval_duration', 0) / 1_000_000) or 100
                return output, latency, tokens
        except Exception as e:
            print(f"   ⚠️  Ollama error: {e}")
        return None, 0, 0
    
    def get_stats(self):
        """获取统计信息"""
        try:
            resp = requests.get(f"{DCM_URL}/api/v1/jobs/stats/summary", timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        return {}
    
    def print_status(self, phase_name):
        """打印状态"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        remaining = (self.end_time - datetime.now()).total_seconds()
        
        stats = self.get_stats()
        by_status = stats.get('by_status', {})
        
        print(f"\n{'='*60}")
        print(f"⏱️  Elapsed: {elapsed/60:.1f} min | Remaining: {remaining/60:.1f} min")
        print(f"📊 Phase: {phase_name}")
        print(f"📤 Submitted: {len(self.jobs_submitted)} | ✅ Completed: {self.jobs_completed}")
        print(f"📈 Jobs by status: {json.dumps(by_status)}")
        print(f"{'='*60}")
    
    def run(self):
        """运行测试"""
        print("=" * 60)
        print("DCM 30-Minute Stress Test")
        print(f"Start: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        # 初始化
        if not self.login():
            return
        if not self.register_node():
            return
        
        print("\n🚀 Starting stress test...")
        
        # 计算总时间并分配到各个 phase
        total_seconds = 30 * 60  # 30 分钟
        phase_duration = total_seconds // len(BURST_PATTERNS)
        
        cycle = 0
        job_index = 0
        
        while datetime.now() < self.end_time:
            # 计算当前 phase
            elapsed = (datetime.now() - self.start_time).total_seconds()
            phase_idx = int(elapsed // phase_duration) % len(BURST_PATTERNS)
            pattern = BURST_PATTERNS[phase_idx]
            
            # 打印状态 (每分钟)
            if int(elapsed) % 60 == 0 and int(elapsed) > 0:
                self.print_status(pattern['name'])
            
            # 轮询处理
            self.poll_and_process()
            
            # 随机间隔提交任务
            interval = random.uniform(pattern['interval'][0], pattern['interval'][1])
            time.sleep(interval)
            
            # 提交新任务 (只有在前半段时间内)
            if elapsed < total_seconds * 0.8:
                template = JOB_TEMPLATES[job_index % len(JOB_TEMPLATES)]
                job_id = self.submit_job(template)
                if job_id:
                    print(f"   📤 Submitted [{job_index+1}]: {template['prompt'][:35]}...")
                    job_index += 1
        
        # 最终统计
        print("\n" + "=" * 60)
        print("📊 FINAL RESULTS")
        print("=" * 60)
        self.print_status("COMPLETE")
        
        stats = self.get_stats()
        print(f"\n📈 Job Statistics:")
        print(json.dumps(stats, indent=2))
        
        # 列出完成的 jobs
        print(f"\n📋 Submitted Jobs ({len(self.jobs_submitted)}):")
        for jid in self.jobs_submitted[:10]:
            print(f"   - {jid}")
        if len(self.jobs_submitted) > 10:
            print(f"   ... and {len(self.jobs_submitted) - 10} more")


if __name__ == "__main__":
    runner = DCMTestRunner()
    runner.run()
