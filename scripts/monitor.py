#!/usr/bin/env python3
"""
DCM Real-time Monitor
实时监控 Job 和 Node 的匹配状态

Usage:
    python3 scripts/monitor.py                    # 监控模式
    python3 scripts/monitor.py --once              # 单次检查
    python3 scripts/monitor.py --jobs-only         # 只看 Jobs
    python3 scripts/monitor.py --nodes-only        # 只看 Nodes
"""

import argparse
import requests
import time
import sys
from datetime import datetime
from typing import Optional

# Configuration
API_BASE = "http://localhost:8000/api/v1"
OLLAMA_BASE = "http://localhost:11434"

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[35m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    UNDERLINE = '\033[4m'

def login() -> Optional[str]:
    """Login and get user_id"""
    try:
        resp = requests.post(f"{API_BASE}/users/login", json={
            "email": "user1@example.com",
            "password": "123456"
        }, timeout=5)
        if resp.status_code == 200:
            return resp.json()["user"]["user_id"]
    except:
        pass
    return None


def get_jobs() -> dict:
    """Get all jobs"""
    try:
        resp = requests.get(f"{API_BASE}/jobs", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return {"items": []}


def get_nodes() -> dict:
    """Get all nodes"""
    try:
        resp = requests.get(f"{API_BASE}/nodes", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return {"items": []}


def get_job_escrow(job_id: str) -> dict:
    """Get job escrow info"""
    try:
        resp = requests.get(f"{API_BASE}/jobs/{job_id}/escrow", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return {}


def poll_node(node_id: str) -> dict:
    """Poll a node for jobs"""
    try:
        resp = requests.post(f"{API_BASE}/nodes/{node_id}/poll", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return {}


def check_ollama() -> list:
    """Check available Ollama models"""
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        if resp.status_code == 200:
            return [m["name"] for m in resp.json().get("models", [])]
    except:
        pass
    return []


def print_header():
    """Print header"""
    print(f"\n{Colors.CYAN}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.BOLD}  DCM Real-time Monitor  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.ENDC}")
    print(f"{Colors.CYAN}{'=' * 80}{Colors.ENDC}")


def get_queue_stats() -> dict:
    """Get queue statistics from matching service"""
    try:
        resp = requests.get(f"http://localhost:8000/stats", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("queue_stats", {})
    except:
        pass
    return {}


def print_queue_status():
    """Print queue status"""
    stats = get_queue_stats()
    
    if not stats:
        print(f"\n{Colors.YELLOW}  ⚠️  Queue: unavailable{Colors.ENDC}")
        return
    
    queue_type = stats.get("type", "unknown")
    size = stats.get("size", 0)
    max_size = stats.get("max_size", 0)
    dead_letter = stats.get("dead_letter_size", 0)
    
    # Queue type color
    if "Redis" in queue_type:
        type_color = Colors.CYAN
    else:
        type_color = Colors.GREEN
    
    # Usage indicator
    if max_size > 0:
        usage = size / max_size * 100
        if usage > 90:
            usage_color = Colors.RED
        elif usage > 70:
            usage_color = Colors.YELLOW
        else:
            usage_color = Colors.GREEN
        usage_str = f"{usage_color}{usage:.1f}%{Colors.ENDC}"
    else:
        usage_str = Colors.DIM + "N/A" + Colors.ENDC
    
    print(f"\n{Colors.BOLD}  📊 QUEUE{Colors.ENDC}")
    print(f"  {'-' * 76}")
    print(f"    Type:     {type_color}{queue_type}{Colors.ENDC}")
    print(f"    Size:     {size} / {max_size} ({usage_str})")
    print(f"    Dead:     {Colors.RED if dead_letter > 0 else Colors.GREEN}{dead_letter}{Colors.ENDC}")


def print_jobs_summary(jobs: list, show_details: bool = False):
    """Print jobs summary"""
    if not jobs:
        print(f"\n{Colors.YELLOW}  No jobs found{Colors.ENDC}")
        return
    
    # Count by status
    status_counts = {}
    model_counts = {}
    for job in jobs:
        status = job["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        
        model = job["model"]
        key = f"{model}|{status}"
        model_counts[key] = model_counts.get(key, 0) + 1
    
    # Status colors
    status_colors = {
        "pending": Colors.YELLOW,
        "matched": Colors.CYAN,
        "completed": Colors.GREEN,
        "failed": Colors.RED,
    }
    
    print(f"\n{Colors.BOLD}  📋 JOBS ({len(jobs)} total){Colors.ENDC}")
    print(f"  {'-' * 76}")
    
    # By status
    print(f"  {Colors.BOLD}By Status:{Colors.ENDC}")
    for status, count in sorted(status_counts.items()):
        color = status_colors.get(status, Colors.ENDC)
        print(f"    {color}{status:12}{Colors.ENDC}: {count}")
    
    # By model
    print(f"\n  {Colors.BOLD}By Model:{Colors.ENDC}")
    models = {}
    for key, count in model_counts.items():
        model, status = key.split("|")
        if model not in models:
            models[model] = {}
        models[model][status] = count
    
    for model, counts in sorted(models.items()):
        print(f"    {Colors.BLUE}{model}{Colors.ENDC}:", end=" ")
        parts = [f"{status}={c}" for status, c in counts.items()]
        print(", ".join(parts))
    
    # Show recent jobs
    if show_details:
        print(f"\n  {Colors.BOLD}Recent Jobs:{Colors.ENDC}")
        for job in jobs[-5:]:
            status = job["status"]
            color = status_colors.get(status, Colors.ENDC)
            print(f"    {color}{job['job_id'][:12]}...{Colors.ENDC} | {job['model']:15} | {status:10}")


def print_nodes_summary(nodes: list, show_details: bool = False):
    """Print nodes summary"""
    if not nodes:
        print(f"\n{Colors.YELLOW}  No nodes found{Colors.ENDC}")
        return
    
    online_nodes = [n for n in nodes if n["status"] == "online"]
    
    print(f"\n{Colors.BOLD}  🖥️  NODES ({len(nodes)} total, {len(online_nodes)} online){Colors.ENDC}")
    print(f"  {'-' * 76}")
    
    # Online nodes
    for node in online_nodes:
        # Get node details
        try:
            resp = requests.get(f"{API_BASE}/nodes/{node['node_id']}", timeout=3)
            if resp.status_code == 200:
                details = resp.json()
                model = details.get("model", "N/A")
                runtime = details.get("runtime", "N/A")
                region = details.get("region", "N/A")
            else:
                model = runtime = region = "N/A"
        except:
            model = runtime = region = "N/A"
        
        print(f"    {Colors.GREEN}●{Colors.ENDC} {node['node_id'][:12]}... | {model:15} | {runtime:8} | {region}")
    
    # Offline nodes
    for node in nodes:
        if node["status"] != "online":
            print(f"    {Colors.RED}○{Colors.ENDC} {node['node_id'][:12]}... | {node['status']}")


def get_orphan_nodes() -> list:
    """Get orphan nodes from API"""
    try:
        resp = requests.get(f"http://localhost:8000/internal/v1/nodes/orphans", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("orphan_nodes", [])
    except:
        pass
    return []


def print_orphan_nodes():
    """Print orphan nodes (nodes with user_id but not in user's node_ids)"""
    orphans = get_orphan_nodes()
    
    if not orphans:
        return  # No orphans, skip
    
    print(f"\n{Colors.RED}{Colors.BOLD}  ⚠️  ORPHAN NODES ({len(orphans)}){Colors.ENDC}")
    print(f"  {'-' * 76}")
    print(f"  {Colors.DIM}Nodes have user_id but not in user's node_ids list:{Colors.ENDC}")
    
    for orphan in orphans:
        node_id = orphan["node_id"][:12] + "..."
        user_id = orphan.get("user_id", "unknown")[:12] + "..."
        reason = orphan.get("reason", "unknown")
        gpu = orphan.get("gpu_type", "N/A")
        
        reason_color = Colors.RED if reason == "user_not_found" else Colors.YELLOW
        print(f"    {Colors.RED}✗{Colors.ENDC} {node_id} | User: {user_id} | {gpu:12} | {reason_color}{reason}{Colors.ENDC}")


def print_ollama_status():
    """Print Ollama status"""
    models = check_ollama()
    if models:
        print(f"\n{Colors.BOLD}  🤖 OLLAMA MODELS{Colors.ENDC}")
        print(f"  {'-' * 76}")
        for model in models:
            print(f"    {Colors.GREEN}✓{Colors.ENDC} {model}")
    else:
        print(f"\n{Colors.RED}  ⚠️  Ollama not available{Colors.ENDC}")


def monitor_mode(interval: int = 2, jobs_only: bool = False, nodes_only: bool = False):
    """Monitor mode - continuous monitoring like 'top'"""
    print(f"\n{Colors.GREEN}  Starting real-time monitor (Ctrl+C to stop){Colors.ENDC}")
    print(f"  Refresh interval: {interval}s\n")
    
    # Cache for changes tracking
    prev_job_count = 0
    prev_completed = 0
    
    try:
        iteration = 0
        while True:
            iteration += 1
            
            # Clear screen and move cursor to top
            print("\033[2J", end="")  # Clear screen
            print("\033[H", end="")   # Move cursor to home
            
            print_header()
            
            if not jobs_only:
                nodes = get_nodes()["items"]
                print_nodes_summary(nodes)
                # Show orphan nodes in all modes
                print_orphan_nodes()
            
            if not nodes_only:
                jobs = get_jobs()["items"]
                
                # Track changes
                completed = len([j for j in jobs if j["status"] == "completed"])
                pending = len([j for j in jobs if j["status"] == "pending"])
                matched = len([j for j in jobs if j["status"] == "matched"])
                
                # Highlight changes
                new_completed = completed - prev_completed
                if new_completed > 0:
                    print(f"\n  {Colors.GREEN}🆕 +{new_completed} completed!{Colors.ENDC}")
                
                prev_job_count = len(jobs)
                prev_completed = completed
                
                print_jobs_summary(jobs, show_details=(iteration % 5 == 0))
            
            print_queue_status()
            print_ollama_status()
            
            print(f"\n{Colors.DIM}  [{iteration}] Press Ctrl+C to stop{Colors.ENDC}")
            
            # Flush output
            sys.stdout.flush()
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\n{Colors.GREEN}  ✓ Monitor stopped.{Colors.ENDC}\n")
        sys.exit(0)


def once_mode():
    """Single check mode"""
    print_header()
    
    # Login
    user_id = login()
    if user_id:
        print(f"\n  {Colors.GREEN}✓{Colors.ENDC} Logged in as: {user_id[:8]}...")
    else:
        print(f"\n  {Colors.YELLOW}⚠{Colors.ENDC} Not logged in")
    
    # Nodes
    nodes = get_nodes()["items"]
    print_nodes_summary(nodes, show_details=True)
    
    # Jobs
    jobs = get_jobs()["items"]
    print_jobs_summary(jobs, show_details=True)
    
    # Ollama
    print_ollama_status()
    
    # Queue status
    print_queue_status()
    
    # Orphan nodes
    print_orphan_nodes()
    
    # Escrow summary
    print(f"\n{Colors.BOLD}  💰 ESCROW SUMMARY{Colors.ENDC}")
    print(f"  {'-' * 76}")
    
    total_locked = 0
    total_spent = 0
    total_refund = 0
    
    for job in jobs[:20]:  # Check first 20 jobs
        escrow = get_job_escrow(job["job_id"])
        total_locked += escrow.get("locked_amount", 0) or 0
        total_spent += escrow.get("spent_amount", 0) or 0
        total_refund += escrow.get("refund_amount", 0) or 0
    
    print(f"    Locked: {total_locked:.8f} USDC")
    print(f"    Spent:  {total_spent:.8f} USDC")
    print(f"    Refund: {total_refund:.8f} USDC")
    
    if total_spent > 0:
        print(f"\n    Distribution (if settled):")
        print(f"      Node (95%):     {total_spent * 0.95:.10f} USDC")
        print(f"      Platform (5%):  {total_spent * 0.05:.10f} USDC")
    
    print()


def test_matching():
    """Test matching with jobs"""
    import hashlib
    
    print_header()
    print(f"\n{Colors.BOLD}  🧪 MATCHING TEST MODE{Colors.ENDC}")
    print(f"  {'-' * 76}\n")
    
    # Login
    user_id = login()
    if not user_id:
        print(f"  {Colors.RED}✗{Colors.ENDC} Login failed")
        return
    
    print(f"  {Colors.GREEN}✓{Colors.ENDC} Logged in as: {user_id[:8]}...")
    
    # Get node
    nodes = get_nodes()["items"]
    if not nodes:
        print(f"  {Colors.RED}✗{Colors.ENDC} No nodes available")
        return
    
    online_nodes = [n for n in nodes if n["status"] == "online"]
    if not online_nodes:
        print(f"  {Colors.RED}✗{Colors.ENDC} No online nodes")
        return
    
    node_id = online_nodes[0]["node_id"]
    print(f"  {Colors.GREEN}✓{Colors.ENDC} Using node: {node_id[:12]}...")
    
    # Test prompts
    prompts = [
        ("qwen2.5:7b", "What is 2+2?"),
        ("qwen2.5:7b", "What is the capital of France?"),
        ("qwen2.5:7b", "Explain AI in one sentence."),
    ]
    
    print(f"\n  {Colors.BOLD}Submitting test jobs...{Colors.ENDC}")
    
    for model, prompt in prompts:
        resp = requests.post(f"{API_BASE}/jobs", json={
            "model": model,
            "input_tokens": len(prompt.split()),
            "output_tokens_limit": 50,
            "bid_price": 0.001,
            "max_latency": 30000,
            "prompt": prompt
        }, timeout=5)
        
        if resp.status_code == 200:
            job_id = resp.json()["job_id"]
            print(f"    {Colors.GREEN}✓{Colors.ENDC} {model}: {prompt[:30]}... -> {job_id[:12]}...")
        else:
            print(f"    {Colors.RED}✗{Colors.ENDC} Failed: {prompt[:30]}...")
    
    # Poll and process
    print(f"\n  {Colors.BOLD}Processing jobs...{Colors.ENDC}")
    
    for i in range(10):
        resp = requests.post(f"{API_BASE}/nodes/{node_id}/poll", timeout=5)
        data = resp.json()
        job_id = data.get("job_id")
        
        if not job_id:
            time.sleep(0.5)
            continue
        
        input_data = data.get("input", {})
        messages = input_data.get("messages", [])
        prompt = messages[-1]["content"] if messages else ""
        match_id = data.get("execution_id", "").replace("exec_", "match_")
        model = data.get("model", "qwen2.5:7b")
        
        print(f"\n  {Colors.CYAN}[{i+1}]{Colors.ENDC} Processing: {prompt[:40]}...")
        
        # Call Ollama
        try:
            ollama = requests.post(f"{OLLAMA_BASE}/api/generate", json={
                "model": model,
                "prompt": prompt,
                "stream": False
            }, timeout=30)
            
            if ollama.status_code == 200:
                result = ollama.json()
                output = result.get("response", "").strip()
                tokens = result.get("eval_count", len(output.split()))
                latency = int(result.get("eval_duration", 0) / 1_000_000)
                
                print(f"       🤖 {output[:50]}...")
                print(f"       📊 {tokens} tokens, {latency}ms")
                
                # Submit result
                resp = requests.post(
                    f"{API_BASE}/nodes/{node_id}/jobs/{job_id}/result",
                    json={
                        "match_id": match_id,
                        "result": output,
                        "result_hash": hashlib.sha256(output.encode()).hexdigest()[:16],
                        "actual_latency_ms": latency,
                        "actual_tokens": tokens
                    },
                    timeout=5
                )
                
                if resp.status_code == 200:
                    print(f"       {Colors.GREEN}✓ Submitted{Colors.ENDC}")
                else:
                    print(f"       {Colors.RED}✗ Submit failed: {resp.text[:50]}{Colors.ENDC}")
            else:
                print(f"       {Colors.RED}✗ Ollama error: {ollama.status_code}{Colors.ENDC}")
        except Exception as e:
            print(f"       {Colors.RED}✗ Error: {e}{Colors.ENDC}")
    
    # Final summary
    print(f"\n  {Colors.BOLD}Final Status:{Colors.ENDC}")
    jobs = get_jobs()["items"]
    status_counts = {}
    for job in jobs:
        status = job["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in sorted(status_counts.items()):
        print(f"    {status}: {count}")


def main():
    parser = argparse.ArgumentParser(description="DCM Real-time Monitor")
    parser.add_argument("--once", action="store_true", help="Single check mode")
    parser.add_argument("--jobs-only", action="store_true", help="Show only jobs")
    parser.add_argument("--nodes-only", action="store_true", help="Show only nodes")
    parser.add_argument("--test", action="store_true", help="Test matching mode")
    parser.add_argument("--interval", type=int, default=2, help="Refresh interval (seconds)")
    
    args = parser.parse_args()
    
    if args.test:
        test_matching()
    elif args.once or args.jobs_only or args.nodes_only:
        once_mode()
    else:
        monitor_mode(interval=args.interval, 
                      jobs_only=args.jobs_only, 
                      nodes_only=args.nodes_only)


if __name__ == "__main__":
    main()
