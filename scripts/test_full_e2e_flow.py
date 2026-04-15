#!/usr/bin/env python3
"""
Full E2E Test - 完整流程测试
API: Create Job → Match → Poll → Execute (Ollama) → Submit Result
"""

import requests
import json
import time
import sys
import hashlib
import base64
import uuid
from datetime import datetime

# 配置
DCM_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:7b"
TEST_USER_ID = str(uuid.uuid4())  # 必须使用 UUID 格式

class E2ETest:
    def __init__(self):
        self.node_id = None
        self.job_id = None
        self.match_id = None
        self.user_id = None
        
    def log(self, msg, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [{level}] {msg}")
    
    def log_step(self, step, msg):
        print(f"\n{'='*60}")
        print(f"STEP {step}: {msg}")
        print(f"{'='*60}")
    
    def check_server(self):
        """检查服务器"""
        self.log("检查 DCM 服务器...")
        try:
            resp = requests.get(f"{DCM_URL}/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self.log(f"DCM 服务器正常: v{data.get('version', '?')}")
                return True
        except Exception as e:
            self.log(f"DCM 服务器不可用: {e}", "ERROR")
            return False
    
    def check_ollama(self):
        """检查 Ollama"""
        self.log("检查 Ollama...")
        try:
            resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m.get("name") for m in models]
                self.log(f"Ollama 正常: {model_names}")
                if MODEL in model_names:
                    self.log(f"模型 {MODEL} 可用")
                    return True
                else:
                    self.log(f"模型 {MODEL} 不可用", "WARN")
                    return True  # 继续测试
        except Exception as e:
            self.log(f"Ollama 不可用: {e}", "ERROR")
            return False
    
    # ===== STEP 0: 注册用户 =====
    def register_user(self):
        self.log_step(0, "注册用户")
        
        import random
        user_data = {
            "email": f"test-{random.randint(1000,9999)}@example.com",
            "password": "test123456",
            "wallet_address": f"0x{''.join([format(random.randint(0, 15), 'x') for _ in range(40)])}",
        }
        
        try:
            resp = requests.post(f"{DCM_URL}/api/v1/users/register", json=user_data, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK":
                    self.user_id = data.get("user_id")
                    self.log(f"用户注册成功: {self.user_id}")
                    return True
                else:
                    self.log(f"用户注册失败: {data.get('error')}", "WARN")
                    # 尝试登录获取 user_id
                    return self.login_user(user_data)
            else:
                self.log(f"用户注册失败: {resp.status_code}", "WARN")
                return self.login_user(user_data)
        except Exception as e:
            self.log(f"用户注册异常: {e}", "ERROR")
            return False
    
    def login_user(self, user_data):
        """登录用户"""
        try:
            resp = requests.post(f"{DCM_URL}/api/v1/users/login", json={
                "email": user_data.get("email"),
                "password": user_data.get("password"),
            }, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK":
                    self.user_id = data.get("user_id")
                    self.log(f"用户登录成功: {self.user_id}")
                    return True
        except:
            pass
        
        self.log("无法获取 user_id", "ERROR")
        return False
    
    # ===== STEP 1: 注册 Node =====
    def register_node(self):
        self.log_step(1, "注册 Node")
        
        node_config = {
            "user_id": self.user_id,
            "runtime": {
                "type": "ollama",
                "loaded_models": [MODEL],
            },
            "hardware": {
                "gpu_type": "NVIDIA RTX (Local)",
                "gpu_count": 1,
            },
            "location": {
                "region": "local",
            },
            "pricing": {
                "ask_price": 0.000001,  # USDC per token
            },
            "model_support": [MODEL],
            "ask_price": 0.000001,
            "avg_latency": 100,
        }
        
        self.log(f"注册 Node: user_id={TEST_USER_ID}")
        self.log(f"配置: {json.dumps(node_config, indent=2)}")
        
        try:
            resp = requests.post(f"{DCM_URL}/api/v1/nodes", json=node_config, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                self.node_id = data.get("node_id")
                self.log(f"Node 注册成功: {self.node_id}")
                return True
            else:
                self.log(f"Node 注册失败: {resp.status_code} - {resp.text}", "ERROR")
                return False
        except Exception as e:
            self.log(f"Node 注册异常: {e}", "ERROR")
            return False
    
    # ===== STEP 2: Node 上线 =====
    def node_online(self):
        self.log_step(2, "Node 上线")
        
        self.log(f"激活 Node: {self.node_id}")
        
        try:
            # 先尝试 deposit stake (如果需要)
            try:
                resp = requests.post(
                    f"{DCM_URL}/api/v1/nodes/{self.node_id}/stake/deposit",
                    json={"tx_hash": "mock-tx-hash"},
                    timeout=10
                )
                self.log(f"Stake deposit: {resp.status_code}")
            except:
                pass  # 可能不需要 stake
            
            # 上线
            resp = requests.post(f"{DCM_URL}/api/v1/nodes/{self.node_id}/online", timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                self.log(f"Node 上线成功: {data.get('status')}")
                
                # 发送 live_status 来激活节点 (关键!)
                self._send_live_status()
                
                return True
            else:
                self.log(f"Node 上线失败: {resp.status_code} - {resp.text}", "ERROR")
                return False
        except Exception as e:
            self.log(f"Node 上线异常: {e}", "ERROR")
            return False
    
    def _send_live_status(self):
        """发送 live_status 来激活节点"""
        try:
            resp = requests.post(
                f"{DCM_URL}/api/v1/nodes/{self.node_id}/live_status",
                json={
                    "timestamp": int(time.time() * 1000),
                    "status": {"status": "online"},
                    "capacity": {"max_concurrency_total": 2},
                    "load": {"active_jobs": 0, "available_token_capacity": 1000}
                },
                timeout=10
            )
            if resp.status_code == 200:
                self.log(f"Live status 发送成功")
            else:
                self.log(f"Live status 失败: {resp.status_code}", "WARN")
        except Exception as e:
            self.log(f"Live status 异常: {e}", "WARN")
    
    # ===== STEP 3: Node 上报状态 =====
    def report_capacity(self):
        self.log_step(3, "Node 上报状态")
        
        capacity_report = {
            "timestamp": int(time.time() * 1000),
            "runtime": {
                "type": "ollama",
                "loaded_models": [MODEL],
            },
            "ask_price": 0.000001,
            "avg_latency": 100,
            "gpu_count": 1,
            "capacity": {
                "max_concurrency_total": 2,
            },
        }
        
        try:
            resp = requests.post(
                f"{DCM_URL}/api/v1/nodes/{self.node_id}/capacity_report",
                json=capacity_report,
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                cluster_id = data.get("new_cluster_id")
                self.log(f"Capacity report 成功: cluster_id={cluster_id}")
                return True
            else:
                self.log(f"Capacity report 失败: {resp.status_code}", "WARN")
                return True  # 继续
        except Exception as e:
            self.log(f"Capacity report 异常: {e}", "WARN")
            return True
    
    # ===== STEP 4: 创建 Job =====
    def create_job(self, prompt="Hello! What is 1+1? Answer briefly."):
        self.log_step(4, "创建 Job (OpenAI 格式)")
        
        job_request = {
            "model": MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 50,
            "temperature": 0.7,
            "user": self.user_id,
        }
        
        self.log(f"创建 Job: {json.dumps(job_request, indent=2)}")
        
        try:
            resp = requests.post(f"{DCM_URL}/api/v1/jobs/openai", json=job_request, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                self.job_id = data.get("job_id")
                self.log(f"Job 创建成功: {self.job_id}")
                self.log(f"状态: {data.get('status')}")
                self.log(f"Escrow: {data.get('escrow_amount')} USDC")
                return True
            else:
                self.log(f"Job 创建失败: {resp.status_code} - {resp.text}", "ERROR")
                return False
        except Exception as e:
            self.log(f"Job 创建异常: {e}", "ERROR")
            return False
    
    # ===== STEP 5: Node Poll 获取 Job =====
    def poll_job(self):
        self.log_step(5, "Node Poll 获取 Job")
        
        self.log(f"Node {self.node_id} poll...")
        
        try:
            resp = requests.post(f"{DCM_URL}/api/v1/nodes/{self.node_id}/poll", timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                
                if data.get("has_job"):
                    self.job_id = data.get("job_id")
                    self.match_id = data.get("execution_id")
                    
                    self.log(f"获取到 Job!")
                    self.log(f"  job_id: {self.job_id}")
                    self.log(f"  execution_id: {data.get('execution_id')}")
                    self.log(f"  model: {data.get('model')}")
                    
                    # 检查 input 结构
                    model = data.get("model", {})
                    if isinstance(model, dict):
                        self.log(f"  model.name: {model.get('name')}")
                        self.log(f"  model.family: {model.get('family')}")
                    
                    input_data = data.get("input", {})
                    messages = input_data.get("messages", [])
                    if messages:
                        for msg in messages:
                            self.log(f"  message[{msg.get('role')}]: {msg.get('content')[:50]}...")
                    
                    generation = data.get("generation", {})
                    self.log(f"  generation: max_tokens={generation.get('max_tokens')}, temp={generation.get('temperature')}")
                    
                    return True
                else:
                    self.log("没有获取到 Job (等待撮合...)")
                    return False
            else:
                self.log(f"Poll 失败: {resp.status_code} - {resp.text}", "ERROR")
                return False
        except Exception as e:
            self.log(f"Poll 异常: {e}", "ERROR")
            return False
    
    # ===== STEP 6: 调用 Ollama 执行推理 =====
    def execute_ollama(self, prompt):
        self.log_step(6, "调用 Ollama 执行推理")
        
        self.log(f"Prompt: {prompt}")
        
        ollama_payload = {
            "model": MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "options": {
                "temperature": 0.7,
                "num_predict": 50,
            },
            "stream": False,
        }
        
        start_time = time.time()
        
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json=ollama_payload,
                timeout=120
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            if resp.status_code == 200:
                data = resp.json()
                output = data.get("message", {}).get("content", "")
                output_tokens = data.get("eval_count", len(output.split()))
                prompt_tokens = data.get("prompt_eval_count", len(prompt.split()) // 4)
                
                self.log(f"Ollama 执行成功!")
                self.log(f"  输出: {output}")
                self.log(f"  Latency: {latency_ms}ms")
                self.log(f"  Output tokens: {output_tokens}")
                self.log(f"  Prompt tokens: {prompt_tokens}")
                
                return {
                    "output": output,
                    "latency_ms": latency_ms,
                    "output_tokens": output_tokens,
                    "prompt_tokens": prompt_tokens,
                }
            else:
                self.log(f"Ollama 执行失败: {resp.status_code} - {resp.text}", "ERROR")
                return None
        except Exception as e:
            self.log(f"Ollama 执行异常: {e}", "ERROR")
            return None
    
    # ===== STEP 7: 提交结果 =====
    def submit_result(self, output, latency_ms, output_tokens):
        self.log_step(7, "提交结果")
        
        # Base64 编码
        encoded_result = base64.b64encode(output.encode()).decode()
        result_hash = hashlib.sha256(output.encode()).hexdigest()
        
        # 获取 match_id
        match_id = self.match_id.replace("exec_", "match_") if self.match_id else None
        
        result_payload = {
            "match_id": match_id,
            "result": encoded_result,
            "result_hash": result_hash,
            "actual_latency_ms": latency_ms,
            "actual_tokens": output_tokens,  # 注意: 是 actual_tokens 不是 actual_output_tokens
        }
        
        self.log(f"提交结果: job_id={self.job_id}")
        self.log(f"  output: {output[:50]}...")
        self.log(f"  latency: {latency_ms}ms")
        self.log(f"  tokens: {output_tokens}")
        self.log(f"  match_id: {match_id}")
        
        try:
            resp = requests.post(
                f"{DCM_URL}/api/v1/nodes/{self.node_id}/jobs/{self.job_id}/result",
                json=result_payload,
                timeout=30
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.log(f"结果提交成功!")
                self.log(f"  layer: {data.get('layer', 1)}")
                self.log(f"  match_id: {data.get('match_id')}")
                return True
            else:
                self.log(f"结果提交失败: {resp.status_code} - {resp.text}", "ERROR")
                return False
        except Exception as e:
            self.log(f"结果提交异常: {e}", "ERROR")
            return False
    
    # ===== STEP 8: 验证 Job 状态 =====
    def verify_job_status(self):
        self.log_step(8, "验证 Job 状态")
        
        try:
            resp = requests.get(f"{DCM_URL}/api/v1/jobs/{self.job_id}", timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                self.log(f"Job 状态:")
                self.log(f"  status: {data.get('status')}")
                self.log(f"  result: {data.get('result', 'N/A')[:100] if data.get('result') else 'N/A'}")
                self.log(f"  actual_output_tokens: {data.get('actual_output_tokens')}")
                self.log(f"  final_price: {data.get('final_price')}")
                
                escrow = data.get("escrow", {})
                if escrow:
                    self.log(f"  escrow.status: {escrow.get('status')}")
                    self.log(f"  escrow.spent: {escrow.get('spent_amount')}")
                    self.log(f"  escrow.refund: {escrow.get('refund_amount')}")
                
                return data.get("status") == "completed"
            else:
                self.log(f"获取 Job 状态失败: {resp.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"验证异常: {e}", "ERROR")
            return False
    
    # ===== 运行完整流程 =====
    def run(self):
        print("\n" + "="*60)
        print("FULL E2E TEST - 完整流程测试")
        print("="*60)
        print(f"目标: {DCM_URL}")
        print(f"Ollama: {OLLAMA_URL}")
        print(f"Model: {MODEL}")
        print(f"时间: {datetime.now().isoformat()}")
        
        # 检查环境
        if not self.check_server():
            self.log("DCM 服务器不可用，退出", "ERROR")
            return False
        
        if not self.check_ollama():
            self.log("Ollama 不可用，退出", "ERROR")
            return False
        
        # 步骤 0: 注册用户
        if not self.register_user():
            return False
        
        # 步骤 1-3: 注册并上线 Node
        if not self.register_node():
            return False
        
        if not self.node_online():
            return False
        
        self.report_capacity()
        
        # 步骤 4: 创建 Job
        if not self.create_job("What is 2+2? Answer briefly."):
            return False
        
        # 等待撮合
        self.log("等待撮合 (2秒)...")
        time.sleep(2)
        
        # 步骤 5: Poll 获取 Job
        for attempt in range(5):
            if self.poll_job():
                break
            self.log(f"Poll 重试 {attempt + 1}/5...")
            time.sleep(1)
        else:
            self.log("无法获取 Job", "ERROR")
            return False
        
        # 步骤 6: 执行 Ollama
        prompt = "What is 2+2? Answer briefly."
        result = self.execute_ollama(prompt)
        
        if not result:
            return False
        
        # 步骤 7: 提交结果
        if not self.submit_result(
            result["output"],
            result["latency_ms"],
            result["output_tokens"]
        ):
            return False
        
        # 步骤 8: 验证
        time.sleep(1)
        success = self.verify_job_status()
        
        # 汇总
        print("\n" + "="*60)
        print("测试结果")
        print("="*60)
        
        if success:
            print("✅ 完整 E2E 流程测试通过!")
            print(f"   Node ID: {self.node_id}")
            print(f"   Job ID: {self.job_id}")
            return True
        else:
            print("❌ 测试失败")
            return False


def main():
    test = E2ETest()
    success = test.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
