#!/usr/bin/env python3
"""
E2E Test - 10 个 Job 完整流程测试
测试 Create Job → Match → Poll → Ollama → Submit Result 完整流程
"""

import requests
import time
import uuid
import hashlib
import base64
import sys

DCM_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:7b"


def keep_node_online(node_id):
    """保持节点在线"""
    requests.post(f"{DCM_URL}/api/v1/nodes/{node_id}/live_status", json={
        "timestamp": int(time.time() * 1000),
        "status": {"status": "online"},
        "capacity": {"max_concurrency_total": 2},
        "load": {"active_jobs": 0, "available_token_capacity": 1000}
    }, timeout=5)


def setup():
    """初始化测试环境"""
    print("=" * 60)
    print("E2E Test Setup")
    print("=" * 60)
    
    # 1. 注册用户
    print("\n[1] 注册用户...")
    user_data = {
        "email": f"e2e-{uuid.uuid4().hex[:8]}@test.com",
        "password": "test123456",
        "wallet_address": f"0x{uuid.uuid4().hex[:40]}",
    }
    resp = requests.post(f"{DCM_URL}/api/v1/users/register", json=user_data, timeout=10)
    user = resp.json()
    if user.get("status") != "OK":
        raise Exception(f"User registration failed: {user}")
    user_id = user["user_id"]
    print(f"    ✅ User: {user_id}")
    
    # 2. 注册 Node
    print("\n[2] 注册 Node...")
    node_data = {
        "user_id": user_id,
        "runtime": {"type": "ollama", "loaded_models": [MODEL]},
        "hardware": {"gpu_type": "RTX", "gpu_count": 1},
        "pricing": {"ask_price": 0.000001},
    }
    resp = requests.post(f"{DCM_URL}/api/v1/nodes", json=node_data, timeout=10)
    node = resp.json()
    if node.get("status") != "OK":
        raise Exception(f"Node registration failed: {node}")
    node_id = node["node_id"]
    print(f"    ✅ Node: {node_id}")
    
    # 3. Stake & 上线
    print("\n[3] Node 上线...")
    requests.post(f"{DCM_URL}/api/v1/nodes/{node_id}/stake/deposit", json={"tx_hash": "mock"}, timeout=10)
    resp = requests.post(f"{DCM_URL}/api/v1/nodes/{node_id}/online", timeout=10)
    print(f"    ✅ Online")
    
    # 4. 发送状态
    print("\n[4] 发送状态...")
    keep_node_online(node_id)
    requests.post(f"{DCM_URL}/api/v1/nodes/{node_id}/capacity_report", json={
        "timestamp": int(time.time() * 1000),
        "runtime": {"type": "ollama", "loaded_models": [MODEL]},
        "ask_price": 0.000001,
        "avg_latency": 100,
        "gpu_count": 1,
        "capacity": {"max_concurrency_total": 2},
    }, timeout=10)
    print(f"    ✅ Status sent")
    
    time.sleep(0.5)
    
    return user_id, node_id


def run_test(node_id, user_id, test_num, name, prompt):
    """运行单个测试"""
    print(f"\n[TEST {test_num}/10] {name}")
    print(f"    Prompt: \"{prompt[:40]}...\"")
    
    # 保持节点在线（每次测试前都发送）
    keep_node_online(node_id)
    time.sleep(0.2)  # 短暂延迟确保状态更新
    
    # 创建 Job
    job_req = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        "temperature": 0.7,
        "user": user_id,
    }
    resp = requests.post(f"{DCM_URL}/api/v1/jobs/openai", json=job_req, timeout=10)
    job = resp.json()
    job_id = job.get("job_id")
    status = job.get("status")
    print(f"    Job: {job_id} (status: {status})")
    
    # 如果没有立即匹配，等待并 poll
    if status != "matched":
        time.sleep(1)
        keep_node_online(node_id)
        resp = requests.post(f"{DCM_URL}/api/v1/nodes/{node_id}/poll", timeout=10)
        poll = resp.json()
        if poll.get("has_job"):
            job_id = poll.get("job_id")
            print(f"    Polled: {job_id}")
        else:
            print(f"    ❌ Poll failed")
            return False, None
    
    # Poll 获取 Job
    resp = requests.post(f"{DCM_URL}/api/v1/nodes/{node_id}/poll", timeout=10)
    poll = resp.json()
    
    if not poll.get("has_job"):
        print(f"    ❌ No job from poll")
        return False, None
    
    job_id = poll.get("job_id")
    match_id = poll.get("execution_id", "").replace("exec_", "match_")
    model_info = poll.get("model", {})
    
    # 验证 model 格式
    if isinstance(model_info, dict):
        model_name = model_info.get("name", "unknown")
        print(f"    Model: {model_name} (Dict format ✅)")
    else:
        print(f"    Model: {model_info} (String format ⚠️)")
    
    # 执行 Ollama
    start = time.time()
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.7, "num_predict": 50},
        "stream": False,
    }, timeout=120)
    
    if resp.status_code != 200:
        print(f"    ❌ Ollama failed: {resp.status_code}")
        return False, None
    
    data = resp.json()
    output = data.get("message", {}).get("content", "")
    latency_ms = int((time.time() - start) * 1000)
    output_tokens = data.get("eval_count", len(output.split()))
    
    print(f"    Output: \"{output[:40]}...\"")
    print(f"    Latency: {latency_ms}ms, Tokens: {output_tokens}")
    
    # 提交结果
    resp = requests.post(f"{DCM_URL}/api/v1/nodes/{node_id}/jobs/{job_id}/result", json={
        "match_id": match_id,
        "result": base64.b64encode(output.encode()).decode(),
        "result_hash": hashlib.sha256(output.encode()).hexdigest(),
        "actual_latency_ms": latency_ms,
        "actual_tokens": output_tokens,
    }, timeout=30)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"    ✅ Completed! (layer: {result.get('layer', 1)})")
        return True, output
    else:
        print(f"    ❌ Submit failed: {resp.status_code}")
        return False, None


def main():
    print("=" * 60)
    print("E2E Test - 10 Jobs Complete Flow")
    print("=" * 60)
    print(f"DCM: {DCM_URL}")
    print(f"Ollama: {OLLAMA_URL}")
    print(f"Model: {MODEL}")
    
    try:
        user_id, node_id = setup()
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        sys.exit(1)
    
    # 测试用例
    tests = [
        ("Math", "What is 1+1? Answer briefly."),
        ("Joke", "Tell me a short joke."),
        ("Capital", "What is the capital of Japan?"),
        ("Definition", "What is machine learning?"),
        ("List", "List 3 programming languages."),
        ("Color", "What is your favorite color?"),
        ("Science", "What is H2O?"),
        ("History", "Who invented the light bulb?"),
        ("Math2", "What is 10*10?"),
        ("Greeting", "Say hello in 3 words."),
    ]
    
    results = []
    
    for i, (name, prompt) in enumerate(tests):
        success, output = run_test(node_id, user_id, i + 1, name, prompt)
        results.append((name, success, output))
        time.sleep(0.5)  # 短暂延迟
    
    # 汇总
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    passed = 0
    for name, success, output in results:
        status = "✅" if success else "❌"
        out_str = f" -> \"{output[:30]}...\"" if output else ""
        print(f"  {status} {name}{out_str}")
        if success:
            passed += 1
    
    print(f"\n{'=' * 60}")
    print(f"Passed: {passed}/{len(results)}")
    print(f"User: {user_id}")
    print(f"Node: {node_id}")
    print(f"{'=' * 60}")
    
    if passed == len(results):
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {len(results) - passed} tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
