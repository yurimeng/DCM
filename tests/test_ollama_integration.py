#!/usr/bin/env python3
"""
DCM v3.1 - Ollama 集成测试

测试 Ollama 实际调用（需要 Ollama 服务运行）
运行方式:
    # 启动 Ollama
    ollama serve
    
    # 或使用 Docker
    docker run -p 11434:11434 ollama/ollama:latest
    
    # 运行测试
    python tests/test_ollama_integration.py
"""

import asyncio
import aiohttp
import json
import time
from typing import Optional, Dict, Any
import sys

# 配置
OLLAMA_BASE_URL = "http://localhost:11434"
TIMEOUT = 60  # 秒


class OllamaClient:
    """Ollama API 客户端"""
    
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=TIMEOUT)
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def is_healthy(self) -> bool:
        """检查 Ollama 服务是否健康"""
        try:
            async with self.session.get(f"{self.base_url}/api/tags") as resp:
                return resp.status == 200
        except Exception:
            return False
    
    async def list_models(self) -> list[str]:
        """列出可用模型"""
        try:
            async with self.session.get(f"{self.base_url}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["name"] for m in data.get("models", [])]
                return []
        except Exception as e:
            print(f"❌ 获取模型列表失败: {e}")
            return []
    
    async def generate(
        self,
        model: str,
        prompt: str,
        stream: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成文本
        
        Args:
            model: 模型名称
            prompt: 提示词
            stream: 是否流式输出
            options: 额外选项
            
        Returns:
            生成结果
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": options or {},
        }
        
        async with self.session.post(
            f"{self.base_url}/api/generate",
            json=payload,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Ollama API 错误: {resp.status} - {text}")
            
            return await resp.json()


async def test_ollama_connection():
    """测试 Ollama 连接"""
    print("\n" + "=" * 60)
    print("🔗 测试 Ollama 连接")
    print("=" * 60)
    
    async with OllamaClient() as client:
        healthy = await client.is_healthy()
        if not healthy:
            print("❌ Ollama 服务不可用")
            print("   请确保 Ollama 服务正在运行:")
            print("   - 本地: ollama serve")
            print("   - Docker: docker run -p 11434:11434 ollama/ollama")
            return False
        
        print("✅ Ollama 服务连接成功")
        
        models = await client.list_models()
        print(f"📋 可用模型: {len(models)} 个")
        for m in models[:10]:  # 只显示前 10 个
            print(f"   - {m}")
        if len(models) > 10:
            print(f"   ... 还有 {len(models) - 10} 个")
        
        return True


async def test_model_generation(model: str, prompt: str):
    """测试模型生成"""
    print(f"\n🤖 测试模型: {model}")
    print(f"   提示词: {prompt[:50]}...")
    
    async with OllamaClient() as client:
        start = time.time()
        
        try:
            result = await client.generate(model, prompt)
            elapsed = (time.time() - start) * 1000
            
            response = result.get("response", "")
            print(f"✅ 生成成功 ({elapsed:.0f}ms)")
            print(f"   响应: {response[:100]}...")
            
            return True, elapsed
            
        except Exception as e:
            print(f"❌ 生成失败: {e}")
            return False, 0


async def test_model_compatibility():
    """测试模型兼容性"""
    print("\n" + "=" * 60)
    print("🧪 模型兼容性测试")
    print("=" * 60)
    
    # 测试不同模型
    test_cases = [
        ("qwen2.5:7b", "What is 2+2?"),  # 可用模型
        ("qwen3.5:latest", "What is 2+2?"),  # 可用模型
    ]
    
    results = []
    
    for model, prompt in test_cases:
        success, elapsed = await test_model_generation(model, prompt)
        results.append({
            "model": model,
            "success": success,
            "elapsed_ms": elapsed,
        })
        await asyncio.sleep(1)  # 避免请求过快
    
    # 汇总
    print("\n" + "-" * 60)
    print("📊 测试汇总")
    print("-" * 60)
    for r in results:
        status = "✅" if r["success"] else "❌"
        print(f"{status} {r['model']}: {r['elapsed_ms']:.0f}ms")
    
    success_count = sum(1 for r in results if r["success"])
    print(f"\n总计: {success_count}/{len(results)} 成功")
    
    return success_count == len(results)


async def test_concurrent_requests():
    """测试并发请求"""
    print("\n" + "=" * 60)
    print("⚡ 并发请求测试")
    print("=" * 60)
    
    model = "llama3:8b"
    prompt = "Count from 1 to 3:"
    
    async with OllamaClient() as client:
        # 检查模型是否可用
        models = await client.list_models()
        if model not in models:
            print(f"⚠️ 模型 {model} 不可用，跳过测试")
            return True
        
        # 3 个并发请求
        tasks = [
            client.generate(model, f"{prompt} Request {i}")
            for i in range(3)
        ]
        
        start = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = (time.time() - start) * 1000
        
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        
        print(f"并发请求: 3")
        print(f"成功: {success_count}")
        print(f"总耗时: {elapsed:.0f}ms")
        print(f"平均: {elapsed/3:.0f}ms")
        
        return success_count == 3


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("🚀 DCM v3.1 - Ollama 集成测试")
    print("=" * 60)
    
    # 1. 连接测试
    if not await test_ollama_connection():
        print("\n⚠️ Ollama 服务不可用，跳过后续测试")
        print("  如需运行完整测试，请启动 Ollama 服务")
        return
    
    # 2. 模型兼容性测试
    await test_model_compatibility()
    
    # 3. 并发请求测试
    await test_concurrent_requests()
    
    print("\n" + "=" * 60)
    print("✅ 测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
