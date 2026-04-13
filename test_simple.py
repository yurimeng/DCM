#!/usr/bin/env python3
"""简单并发测试"""
import requests
import time

DCM = "https://dcm-api-p00a.onrender.com"

def submit_simple_job():
    """提交简单问候 Job"""
    return requests.post(f"{DCM}/api/v1/jobs", json={
        "model": "qwen2.5:7b",
        "input_tokens": 5,
        "output_tokens_limit": 10,
        "max_latency": 5000,
        "bid_price": 0.001
    }, timeout=10)

def check_stats():
    """检查统计"""
    r = requests.get(f"{DCM}/api/v1/jobs/stats/summary", timeout=5)
    return r.json()

print("=" * 50)
print("简单并发测试 - 提交 5 个问候请求")
print("=" * 50)

print("\n提交中...")
jobs = []
for i in range(5):
    r = submit_simple_job()
    if r.status_code == 200:
        d = r.json()
        jobs.append(d)
        print(f"  [{i+1}] Job: {d.get('job_id', '')[:8]}... | Status: {d.get('status')}")
    else:
        print(f"  [{i+1}] 失败: {r.status_code}")

print(f"\n✓ 成功提交 {len(jobs)} 个 Job")
print("\n等待 Agent 处理...")
print("(Agent 轮询间隔 3 秒)\n")

for i in range(10):
    time.sleep(3)
    stats = check_stats()
    by_status = stats.get("by_status", {})
    completed = by_status.get("completed", 0)
    pending = by_status.get("pending", 0)
    matched = by_status.get("matched", 0)
    
    print(f"[{i*3}s] Pending: {pending} | Matched: {matched} | Completed: {completed}")
    
    if completed >= len(jobs):
        print("\n✓ 所有 Job 已完成!")
        break

print("\n最终统计:")
print(check_stats())
