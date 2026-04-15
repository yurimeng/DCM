#!/usr/bin/env python3
"""
E2E Test - 10 个 Job 创建测试
测试 JobCreateOpenAI API 格式
"""

import requests
import json
import time
import sys
from datetime import datetime

# 配置
DCM_URL = "http://localhost:8000"
USER_ID = "test-user-123"  # 测试用户 ID

def test_job_creation(test_num: int, format_type: str = "openai") -> dict:
    """测试单个 Job 创建"""
    print(f"\n{'='*60}")
    print(f"Test #{test_num}: {format_type} 格式")
    print(f"{'='*60}")
    
    if format_type == "openai":
        # 格式 1: 标准 OpenAI 格式
        payload = {
            "model": "qwen2.5:7b",
            "messages": [
                {"role": "user", "content": f"Hello! This is test #{test_num}. What is 1+1?"}
            ],
            "max_tokens": 50,
            "temperature": 0.7,
            "user": USER_ID,
        }
    elif format_type == "full_dcm":
        # 格式 2: 完整 DCM 格式
        payload = {
            "model": "qwen2.5:7b",
            "messages": [
                {"role": "user", "content": f"Test #{test_num}: Tell me a short joke."}
            ],
            "max_tokens": 100,
            "temperature": 0.8,
            "bid_price": 0.000001,
            "max_latency": 30000,
            "user": USER_ID,
            "callback_url": None,
            "region": "us-west",
            "priority": 5,
        }
    elif format_type == "prompt":
        # 格式 3: 兼容 prompt 格式
        payload = {
            "prompt": f"Test #{test_num}: What is the capital of France?",
            "bid_price": 0.000002,
            "max_latency": 20000,
            "user": USER_ID,
        }
    elif format_type == "system":
        # 格式 4: 带 system message
        payload = {
            "model": "qwen2.5:7b",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Test #{test_num}"}
            ],
            "max_tokens": 30,
            "user": USER_ID,
        }
    else:
        # 格式 5: 最小格式
        payload = {
            "messages": [
                {"role": "user", "content": f"Test #{test_num}: Hi!"}
            ],
        }
    
    start_time = time.time()
    
    try:
        response = requests.post(
            f"{DCM_URL}/api/v1/jobs/openai",
            json=payload,
            timeout=30,
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        print(f"Request: {json.dumps(payload, indent=2)[:200]}...")
        print(f"Status: {response.status_code}")
        print(f"Elapsed: {elapsed_ms:.0f}ms")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Response: {json.dumps(result, indent=2)}")
            return {
                "success": True,
                "test_num": test_num,
                "format": format_type,
                "job_id": result.get("job_id"),
                "status": result.get("status"),
                "elapsed_ms": elapsed_ms,
                "response": result,
            }
        else:
            print(f"Error: {response.text}")
            return {
                "success": False,
                "test_num": test_num,
                "format": format_type,
                "error": response.text,
                "elapsed_ms": elapsed_ms,
            }
            
    except Exception as e:
        print(f"Exception: {e}")
        return {
            "success": False,
            "test_num": test_num,
            "format": format_type,
            "error": str(e),
        }


def check_server():
    """检查服务器是否运行"""
    try:
        response = requests.get(f"{DCM_URL}/health", timeout=5)
        if response.status_code == 200:
            print(f"✓ Server is running at {DCM_URL}")
            return True
    except Exception as e:
        print(f"✗ Server not running: {e}")
        print(f"\n请先启动服务器:")
        print(f"  cd /Users/yurimeng/Code/Platform/DCM")
        print(f"  uvicorn src.main:app --reload --host 0.0.0.0 --port 8000")
        return False
    return False


def main():
    print("=" * 60)
    print("E2E Test - 10 个 Job 创建测试")
    print("=" * 60)
    print(f"Target: {DCM_URL}/api/v1/jobs/openai")
    print(f"Time: {datetime.now().isoformat()}")
    
    # 检查服务器
    if not check_server():
        sys.exit(1)
    
    # 测试用例定义
    test_cases = [
        ("openai", "标准 OpenAI 格式"),
        ("full_dcm", "完整 DCM 格式"),
        ("prompt", "兼容 prompt 格式"),
        ("system", "带 system message"),
        ("minimal", "最小格式"),
    ]
    
    results = []
    
    # 运行 10 个测试 (每个格式 2 次)
    for i in range(10):
        format_type, desc = test_cases[i % len(test_cases)]
        result = test_job_creation(i + 1, format_type)
        results.append(result)
        time.sleep(0.5)  # 避免太快
    
    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count
    
    print(f"\n总计: {len(results)} 个测试")
    print(f"成功: {success_count}")
    print(f"失败: {fail_count}")
    
    # 按格式统计
    print("\n按格式统计:")
    for format_type, _ in test_cases:
        format_results = [r for r in results if r["format"] == format_type]
        success = sum(1 for r in format_results if r["success"])
        print(f"  {format_type}: {success}/{len(format_results)}")
    
    # 详细结果
    print("\n详细结果:")
    for r in results:
        status = "✓" if r["success"] else "✗"
        job_id = r.get("job_id", "N/A")[:20] if r.get("job_id") else "N/A"
        print(f"  {status} Test#{r['test_num']:2d} [{r['format']:10s}] "
              f"job_id={job_id}... ({r['elapsed_ms']:.0f}ms)")
    
    if fail_count > 0:
        print("\n失败详情:")
        for r in results:
            if not r["success"]:
                print(f"  Test#{r['test_num']}: {r.get('error', 'Unknown error')}")
        sys.exit(1)
    else:
        print("\n✓ 所有测试通过!")
        sys.exit(0)


if __name__ == "__main__":
    main()
