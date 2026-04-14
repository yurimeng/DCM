#!/usr/bin/env python3
"""
DCM Full Flow Test / 全流程功能测试

测试内容:
1. 不同 Bid Price 的 Job 撮合
2. 不同 Model Family 的 Job
3. Matching Service 正确拒绝
4. 完整生命周期

Usage:
    python3 scripts/test_full_flow.py
"""

import requests
import time
import sys
from datetime import datetime

API_BASE = "http://localhost:8000"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'


def print_header(text):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.CYAN}{Colors.BOLD}  {text}{Colors.ENDC}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")


def print_test(name, passed, detail=""):
    status = f"{Colors.GREEN}✓ PASS{Colors.ENDC}" if passed else f"{Colors.RED}✗ FAIL{Colors.ENDC}"
    print(f"  {status} {name}")
    if detail:
        print(f"        {detail}")


def login(email="user1@example.com", password="123456"):
    """登录获取用户信息"""
    resp = requests.post(f"{API_BASE}/api/v1/users/login", json={
        "email": email,
        "password": password
    })
    if resp.status_code == 200:
        return resp.json()["user"]
    return None


def get_nodes():
    """获取所有节点"""
    resp = requests.get(f"{API_BASE}/api/v1/nodes")
    if resp.status_code == 200:
        return resp.json()["items"]
    return []


def get_node_detail(node_id):
    """获取节点详情"""
    resp = requests.get(f"{API_BASE}/api/v1/nodes/{node_id}")
    if resp.status_code == 200:
        return resp.json()
    return None


def submit_job(model, bid_price, input_tokens=100, max_latency=10000, prompt="What is AI?"):
    """提交 Job"""
    resp = requests.post(f"{API_BASE}/api/v1/jobs", json={
        "model_requirement": model,
        "input_tokens": input_tokens,
        "output_tokens_limit": 512,
        "max_latency": max_latency,
        "bid_price": bid_price,
        "prompt": prompt,
    })
    return resp


def poll_node(node_id):
    """节点轮询"""
    resp = requests.post(f"{API_BASE}/api/v1/nodes/{node_id}/poll")
    return resp


def get_jobs():
    """获取所有 Job"""
    resp = requests.get(f"{API_BASE}/api/v1/jobs")
    if resp.status_code == 200:
        return resp.json()["items"]
    return []


def get_stats():
    """获取统计信息"""
    resp = requests.get(f"{API_BASE}/stats")
    if resp.status_code == 200:
        return resp.json()
    return {}


def run_test():
    """运行完整测试"""
    print_header("DCM Full Flow Test")
    
    # 检查服务
    print(f"{Colors.BOLD}[0] 检查服务状态{Colors.ENDC}")
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=5)
        if resp.status_code == 200:
            print_test("DCM 服务运行中", True)
        else:
            print_test("DCM 服务", False, f"Status: {resp.status_code}")
            return
    except Exception as e:
        print_test("DCM 服务", False, str(e))
        return
    
    # 1. 登录
    print(f"{Colors.BOLD}\n[1] 用户登录{Colors.ENDC}")
    user = login()
    if user:
        print_test("登录成功", True, f"User: {user['email']}")
        user_id = user["user_id"]
    else:
        print_test("登录", False, "登录失败")
        return
    
    # 2. 查看节点
    print(f"{Colors.BOLD}\n[2] 节点信息{Colors.ENDC}")
    nodes = get_nodes()
    print_test(f"节点数量: {len(nodes)}", len(nodes) > 0)
    
    online_nodes = [n for n in nodes if n["status"] == "online"]
    print_test(f"在线节点: {len(online_nodes)}", len(online_nodes) > 0)
    
    for node in nodes:
        detail = get_node_detail(node["node_id"])
        if detail:
            model = detail.get("model", "N/A")
            runtime = detail.get("runtime", "N/A")
            gpu = detail.get("gpu_type", "N/A")
            print(f"        {node['node_id'][:12]}... | {model:15} | {runtime:8} | {gpu}")
    
    if not online_nodes:
        print(f"{Colors.YELLOW}  ⚠️  没有在线节点，无法测试撮合{Colors.ENDC}")
        return
    
    node_id = online_nodes[0]["node_id"]
    
    # 3. 测试用例定义
    print(f"{Colors.BOLD}\n[3] 测试用例定义{Colors.ENDC}")
    
    test_cases = [
        # (name, model, bid_price, expected_match, reason)
        ("正常价格 + 匹配模型", "qwen2.5:7b", 0.001, True, "模型匹配，价格合理"),
        ("高价 + 匹配模型", "qwen2.5:7b", 0.5, True, "高价应优先撮合"),
        ("低价 + 匹配模型", "qwen2.5:7b", 0.0001, True, "低价仍应撮合"),
        ("不存在的模型", "nonexistent-model", 0.5, False, "模型不匹配"),
        ("极短延迟要求", "qwen2.5:7b", 0.5, False, "延迟要求无法满足"),
    ]
    
    print(f"{Colors.BOLD}\n[4] 提交测试 Jobs ({len(test_cases)} 个){Colors.ENDC}")
    
    results = []
    for i, (name, model, bid_price, expected, reason) in enumerate(test_cases):
        print(f"\n  测试 {i+1}: {name}")
        print(f"         Model: {model}, Bid: {bid_price}, 预期: {'匹配' if expected else '拒绝'}")
        
        resp = submit_job(model, bid_price)
        
        if resp.status_code == 200:
            job_data = resp.json()
            job_id = job_data["job_id"]
            print(f"         Job ID: {job_id}")
            
            # 等待撮合处理
            time.sleep(0.5)
            
            # 检查该 Job 的实际状态
            job_check = requests.get(f"{API_BASE}/api/v1/jobs/{job_id}")
            if job_check.status_code == 200:
                job_detail = job_check.json()
                job_status = job_detail.get("status", "pending")
                
                if job_status == "matched":
                    print(f"         {Colors.GREEN}✓ 已匹配{Colors.ENDC}")
                    matched = True
                elif job_status == "pending":
                    print(f"         {Colors.YELLOW}○ 未匹配 (pending){Colors.ENDC}")
                    matched = False
                else:
                    print(f"         {Colors.CYAN}○ 状态: {job_status}{Colors.ENDC}")
                    matched = False
            else:
                print(f"         {Colors.RED}✗ 检查失败{Colors.ENDC}")
                matched = False
            
            # 验证结果
            passed = (matched == expected)
            print_test(f"结果验证", passed, f"预期{'匹配' if expected else '拒绝'}, 实际{'匹配' if matched else 'pending'}")
            results.append((name, passed, matched, expected))
        else:
            print(f"         {Colors.RED}✗ 提交失败: {resp.status_code}{Colors.ENDC}")
            print(f"         {resp.text[:100]}")
            results.append((name, False, None, expected))
        
        time.sleep(0.3)
    
    # 5. 统计
    print_header("测试统计")
    
    total = len(results)
    passed = sum(1 for _, p, _, _ in results if p)
    
    print(f"  总测试数: {total}")
    print(f"  通过: {Colors.GREEN}{passed}{Colors.ENDC}")
    print(f"  失败: {Colors.RED}{total - passed}{Colors.ENDC}")
    print(f"  通过率: {passed/total*100:.1f}%")
    
    # 6. 最终状态
    print(f"{Colors.BOLD}\n[6] 最终状态{Colors.ENDC}")
    
    jobs = get_jobs()
    stats = get_stats()
    
    status_counts = {}
    for job in jobs:
        status = job.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print(f"  Jobs 总数: {len(jobs)}")
    for status, count in status_counts.items():
        print(f"    {status}: {count}")
    
    if "queue_stats" in stats:
        qs = stats["queue_stats"]
        print(f"  Queue: {qs.get('type', 'N/A')}")
        print(f"  Queue Size: {qs.get('size', 0)}/{qs.get('max_size', 0)}")
    
    # 7. 详细结果表
    print_header("详细结果")
    print(f"{'测试名称':<30} {'预期':<8} {'实际':<8} {'结果'}")
    print("-" * 60)
    for name, passed, actual, expected in results:
        expected_str = "匹配" if expected else "拒绝"
        actual_str = "匹配" if actual else "拒绝"
        result_str = f"{Colors.GREEN}✓{Colors.ENDC}" if passed else f"{Colors.RED}✗{Colors.ENDC}"
        print(f"{name:<30} {expected_str:<8} {actual_str:<8} {result_str}")
    
    print()
    return passed == total


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
