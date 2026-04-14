#!/usr/bin/env python3
"""
DCM Multi-Model Compatibility Test
多模型兼容性测试脚本

Usage:
    python3 scripts/test_compatibility.py
"""

import requests
import time
import hashlib
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.monitor import (
    API_BASE, Colors, login, get_nodes, get_jobs, 
    poll_node, check_ollama, print_header
)

def call_ollama(model: str, prompt: str) -> dict:
    """Call Ollama API"""
    try:
        resp = requests.post("http://localhost:11434/api/generate", json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }, timeout=60)
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "response": data.get("response", "").strip(),
                "tokens": data.get("eval_count", 0),
                "latency": int(data.get("eval_duration", 0) / 1_000_000)
            }
    except Exception as e:
        return {"success": False, "error": str(e)}
    
    return {"success": False, "error": f"HTTP {resp.status_code}"}


def submit_job(model: str, prompt: str, input_tokens: int = None) -> str:
    """Submit a job"""
    if input_tokens is None:
        input_tokens = len(prompt.split())
    
    try:
        resp = requests.post(f"{API_BASE}/jobs", json={
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens_limit": 100,
            "bid_price": 0.001,
            "max_latency": 60000,
            "prompt": prompt
        }, timeout=10)
        
        if resp.status_code == 200:
            return resp.json()["job_id"]
    except Exception as e:
        print(f"{Colors.RED}  ✗ Submit error: {e}{Colors.ENDC}")
    
    return None


def process_node_jobs(node_id: str, max_jobs: int = None, model: str = None) -> list:
    """Process jobs from a node"""
    results = []
    
    for i in range(50):  # Max 50 polls
        if max_jobs and len(results) >= max_jobs:
            break
        
        resp = requests.post(f"{API_BASE}/nodes/{node_id}/poll", timeout=10)
        data = resp.json()
        job_id = data.get("job_id")
        
        if not job_id:
            time.sleep(0.5)
            continue
        
        # Get job details
        input_data = data.get("input", {})
        messages = input_data.get("messages", [])
        prompt = messages[-1]["content"] if messages else ""
        match_id = data.get("execution_id", "").replace("exec_", "match_")
        job_model = data.get("model", model or "qwen2.5:7b")
        
        print(f"\n  {Colors.CYAN}[{len(results)+1}]{Colors.ENDC} {prompt[:40]}...")
        print(f"       Model: {job_model}")
        
        # Call Ollama
        result = call_ollama(job_model, prompt)
        
        if result["success"]:
            output = result["response"]
            tokens = result["tokens"]
            latency = result["latency"]
            
            print(f"       🤖 {output[:50]}...")
            print(f"       📊 {tokens} tokens, {latency}ms")
            
            # Submit result
            try:
                resp = requests.post(
                    f"{API_BASE}/nodes/{node_id}/jobs/{job_id}/result",
                    json={
                        "match_id": match_id,
                        "result": output,
                        "result_hash": hashlib.sha256(output.encode()).hexdigest()[:16],
                        "actual_latency_ms": latency,
                        "actual_tokens": tokens
                    },
                    timeout=10
                )
                
                if resp.status_code == 200:
                    print(f"       {Colors.GREEN}✓ Submitted{Colors.ENDC}")
                    results.append({
                        "model": job_model,
                        "prompt": prompt,
                        "response": output,
                        "tokens": tokens,
                        "latency": latency
                    })
                else:
                    print(f"       {Colors.RED}✗ Submit failed{Colors.ENDC}")
            except Exception as e:
                print(f"       {Colors.RED}✗ Error: {e}{Colors.ENDC}")
        else:
            print(f"       {Colors.RED}✗ Ollama error: {result.get('error')}{Colors.ENDC}")
        
        time.sleep(0.3)
    
    return results


def run_batch(name: str, model: str, prompts: list):
    """Run a batch of jobs"""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.BOLD}  📦 {name}: {model} ({len(prompts)} jobs){Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    
    # Submit jobs
    print(f"\n  {Colors.BOLD}Submitting jobs...{Colors.ENDC}")
    for i, prompt in enumerate(prompts):
        job_id = submit_job(model, prompt)
        if job_id:
            print(f"    {Colors.GREEN}✓{Colors.ENDC} [{i+1}] {prompt[:40]}...")
        else:
            print(f"    {Colors.RED}✗{Colors.ENDC} [{i+1}] {prompt[:40]}...")
        time.sleep(0.2)
    
    # Get node
    nodes = get_nodes()["items"]
    online_nodes = [n for n in nodes if n["status"] == "online"]
    
    if not online_nodes:
        print(f"\n  {Colors.RED}✗ No online nodes{Colors.ENDC}")
        return []
    
    node_id = online_nodes[0]["node_id"]
    
    # Process jobs
    print(f"\n  {Colors.BOLD}Processing jobs...{Colors.ENDC}")
    results = process_node_jobs(node_id, max_jobs=len(prompts))
    
    print(f"\n  📊 Batch Result: {len(results)}/{len(prompts)} completed")
    
    return results


def main():
    print_header()
    print(f"\n{Colors.BOLD}  🔬 DCM MULTI-MODEL COMPATIBILITY TEST{Colors.ENDC}")
    print(f"{Colors.BOLD}  {'-' * 76}{Colors.ENDC}\n")
    
    # Check prerequisites
    print(f"  {Colors.BOLD}Prerequisites:{Colors.ENDC}")
    
    user_id = login()
    if user_id:
        print(f"    {Colors.GREEN}✓{Colors.ENDC} Logged in as: {user_id[:8]}...")
    else:
        print(f"    {Colors.RED}✗{Colors.ENDC} Login failed")
        return
    
    models = check_ollama()
    if models:
        print(f"    {Colors.GREEN}✓{Colors.ENDC} Ollama models: {', '.join(models)}")
    else:
        print(f"    {Colors.RED}✗{Colors.ENDC} Ollama not available")
        return
    
    nodes = get_nodes()["items"]
    online = [n for n in nodes if n["status"] == "online"]
    if online:
        print(f"    {Colors.GREEN}✓{Colors.ENDC} Online nodes: {len(online)}")
    else:
        print(f"    {Colors.RED}✗{Colors.ENDC} No online nodes")
        return
    
    # ========================================
    # BATCH 1: qwen2.5:7b
    # ========================================
    prompts_qwen = [
        "What is machine learning?",
        "Explain neural networks.",
        "What is Python?",
        "Define deep learning."
    ]
    
    results_qwen = run_batch("Batch 1", "qwen2.5:7b", prompts_qwen)
    
    # ========================================
    # BATCH 2: gemma4:e4b
    # ========================================
    if "gemma4:e4b" in models:
        prompts_gemma = [
            "What is AI?",
            "Explain algorithms.",
            "What is data?",
            "Define learning."
        ]
        
        results_gemma = run_batch("Batch 2", "gemma4:e4b", prompts_gemma)
    else:
        results_gemma = []
    
    # ========================================
    # SUMMARY
    # ========================================
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.BOLD}  📊 FINAL SUMMARY{Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    
    # By model
    print(f"\n  {Colors.BOLD}By Model:{Colors.ENDC}")
    print(f"    qwen2.5:7b: {len(results_qwen)}/{len(prompts_qwen)} completed")
    if results_gemma:
        print(f"    gemma4:e4b: {len(results_gemma)}/{len(prompts_gemma)} completed")
    
    # Show results
    if results_qwen:
        print(f"\n  {Colors.BOLD}qwen2.5:7b Results:{Colors.ENDC}")
        for i, r in enumerate(results_qwen, 1):
            print(f"    [{i}] Q: {r['prompt'][:40]}...")
            print(f"        A: {r['response'][:60]}...")
            print(f"        📊 {r['tokens']} tokens, {r['latency']}ms")
    
    if results_gemma:
        print(f"\n  {Colors.BOLD}gemma4:e4b Results:{Colors.ENDC}")
        for i, r in enumerate(results_gemma, 1):
            print(f"    [{i}] Q: {r['prompt'][:40]}...")
            print(f"        A: {r['response'][:60]}...")
            print(f"        📊 {r['tokens']} tokens, {r['latency']}ms")
    
    # Job status
    jobs = get_jobs()["items"]
    status_counts = {}
    for job in jobs:
        status = job["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print(f"\n  {Colors.BOLD}Overall Job Status:{Colors.ENDC}")
    for status, count in sorted(status_counts.items()):
        print(f"    {status}: {count}")
    
    print(f"\n{Colors.GREEN}  ✅ TEST COMPLETE!{Colors.ENDC}\n")


if __name__ == "__main__":
    main()
