#!/usr/bin/env python3
"""
批量测试脚本 - 测试 DCM MVP 流程
"""

import requests
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

DCM_URL = "https://dcm-api-p00a.onrender.com"
NODE_ID = "14bede16-a406-42bf-8775-4b19f164ef16"

def submit_job(prefix=""):
    """提交一个 Job"""
    job_data = {
        "model": "qwen2.5:7b",
        "input_tokens": 50,
        "output_tokens_limit": 100,
        "max_latency": 30000,
        "bid_price": 0.002
    }
    
    try:
        resp = requests.post(f"{DCM_URL}/api/v1/jobs", json=job_data, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return {
            "success": True,
            "job_id": result.get("job_id"),
            "status": result.get("status"),
            "prefix": prefix
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "prefix": prefix
        }

def wait_for_completion(job_id, timeout=60):
    """等待 Job 完成"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            # 检查 Escrow 状态
            resp = requests.get(f"{DCM_URL}/api/v1/jobs/{job_id}/escrow", timeout=5)
            if resp.status_code == 200:
                escrow = resp.json()
                if escrow.get("status") == "settled":
                    return {
                        "completed": True,
                        "settled_at": escrow.get("settled_at"),
                        "actual_cost": escrow.get("actual_cost"),
                        "node_earn": escrow.get("node_earn")
                    }
        except:
            pass
        time.sleep(2)
    return {"completed": False}

def run_batch_test(count=5):
    """批量顺序测试"""
    print(f"\n{'='*60}")
    print(f"批量顺序测试: 提交 {count} 个 Job")
    print(f"{'='*60}")
    
    results = []
    
    for i in range(count):
        print(f"\n[{i+1}/{count}] 提交 Job...")
        result = submit_job(prefix=f"Job-{i+1}")
        if result["success"]:
            print(f"  ✓ Job {result['job_id'][:8]}... 状态: {result['status']}")
            results.append(result)
        else:
            print(f"  ✗ 提交失败: {result.get('error')}")
        time.sleep(0.5)
    
    # 等待所有 Job 完成
    print(f"\n等待所有 Job 完成...")
    completed = 0
    for r in results:
        if r["success"]:
            wait_result = wait_for_completion(r["job_id"])
            if wait_result["completed"]:
                completed += 1
                print(f"  ✓ {r['job_id'][:8]}... 完成, 花费: {wait_result['actual_cost']:.2e}")
    
    print(f"\n批量测试完成: {completed}/{len(results)} 成功")
    return results

def run_concurrent_test(count=10):
    """并发测试"""
    print(f"\n{'='*60}")
    print(f"并发测试: 同时提交 {count} 个 Job")
    print(f"{'='*60}")
    
    results = []
    
    # 并发提交
    with ThreadPoolExecutor(max_workers=count) as executor:
        futures = {executor.submit(submit_job, f"Concurrent-{i}"): i for i in range(count)}
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result["success"]:
                print(f"  ✓ 提交成功: {result['job_id'][:8]}...")
            else:
                print(f"  ✗ 提交失败: {result.get('error')}")
    
    # 等待所有 Job 完成
    print(f"\n等待所有并发 Job 完成...")
    time.sleep(5)  # 等待处理
    
    completed_results = []
    for r in results:
        if r["success"]:
            wait_result = wait_for_completion(r["job_id"], timeout=120)
            wait_result["job_id"] = r["job_id"]
            completed_results.append(wait_result)
            status = "✓" if wait_result["completed"] else "✗"
            cost = wait_result.get("actual_cost", "N/A")
            print(f"  {status} {r['job_id'][:8]}... 完成: {cost}")
    
    success_count = sum(1 for r in completed_results if r["completed"])
    print(f"\n并发测试完成: {success_count}/{len(results)} 成功")
    return results

def check_agent_status():
    """检查 Agent 状态"""
    print(f"\n{'='*60}")
    print("检查 Agent 和 DCM 状态")
    print(f"{'='*60}")
    
    try:
        # DCM Stats
        resp = requests.get(f"{DCM_URL}/stats", timeout=5)
        stats = resp.json()
        print(f"\nDCM Stats:")
        print(f"  Online Nodes: {stats['matching']['online_nodes']}")
        print(f"  Pending Jobs: {stats['matching']['pending_jobs']}")
        
        # Node Status
        resp = requests.get(f"{DCM_URL}/api/v1/nodes/{NODE_ID}", timeout=5)
        node = resp.json()
        print(f"\nNode Status:")
        print(f"  Node ID: {node['node_id'][:8]}...")
        print(f"  Status: {node['status']}")
        print(f"  Last Heartbeat: {node.get('last_heartbeat', 'N/A')}")
        
    except Exception as e:
        print(f"  ✗ 检查失败: {e}")

if __name__ == "__main__":
    print("="*60)
    print("DCM MVP 批量测试")
    print("="*60)
    
    # 1. 先检查状态
    check_agent_status()
    
    # 2. 批量顺序测试
    run_batch_test(count=3)
    
    # 3. 再次检查
    check_agent_status()
    
    # 4. 并发测试
    run_concurrent_test(count=5)
    
    # 5. 最终检查
    check_agent_status()
    
    print("\n" + "="*60)
    print("测试完成!")
    print("="*60)
