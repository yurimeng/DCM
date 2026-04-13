# DCM 测试原则

> AI-Native Testing Framework for Decentralized Compute Market
> 
> **版本**: v1.0 | **日期**: 2026-04-13

---

## 一、核心原则

### 1.1 AI-First Testing

| 原则 | 说明 |
|------|------|
| **本地 Ollama** | 所有 AI 推理测试必须使用本地 Ollama |
| **真实模型** | 使用实际模型：qwen, llama, gemma 等 |
| **端到端验证** | 完整的 Job 生命周期测试 |

### 1.2 测试分层

```
┌─────────────────────────────────────────────┐
│           E2E Tests (AI Inference)          │
│   Job → Match → Execute → Result → Settle   │
├─────────────────────────────────────────────┤
│         Integration Tests (Services)         │
│   Match Engine, Pre-Lock, Scoring           │
├─────────────────────────────────────────────┤
│           Unit Tests (Models)               │
│   Slot, Job, Node, Worker                   │
└─────────────────────────────────────────────┘
```

---

## 二、网络状态模拟

### 2.1 网络类型矩阵

| 网络类型 | 协议 | 模拟场景 | 测试用例 |
|----------|------|----------|----------|
| **Direct** | HTTPS/WSS | 节点直连 | ✅ 标准路径 |
| **P2P** | gossipsub | 点对点通信 | ✅ 去中心化 |
| **Relay** | circuit relay | NAT 穿透失败 | ✅ 兜底机制 |
| **Degraded** | Mixed | 网络不稳定 | ⚠️ 容错测试 |

### 2.2 网络状态定义

```python
class NetworkState(Enum):
    ONLINE = "online"           # 正常连接
    P2P_DIRECT = "p2p_direct"   # P2P 直连
    P2P_RELAY = "p2p_relay"     # P2P 中继
    OFFLINE = "offline"         # 断开连接
    TIMEOUT = "timeout"         # 超时
    DEGRADED = "degraded"       # 降级模式
```

### 2.3 网络切换测试

```
Test Case: 网络状态切换

1. Node 上线 (HTTPS)
   ↓
2. 切换到 P2P 模式
   ↓
3. 验证 Job 继续执行
   ↓
4. P2P 断开，切换到 Relay
   ↓
5. 验证 Job 继续执行
   ↓
6. Relay 也断开
   ↓
7. 验证超时处理和重连
```

---

## 三、模型测试矩阵

### 3.1 支持的模型

| 模型家族 | 模型版本 | 上下文 | 测试优先级 |
|----------|----------|--------|------------|
| **Qwen** | qwen2.5:7b | 32K | P0 |
| **Qwen** | qwen3:8b | 32K | P0 |
| **Qwen** | qwen3.5:latest | 32K | P1 |
| **Llama** | llama3:8b | 8K | P1 |
| **Llama** | llama3.2:3b | 8K | P2 |
| **Gemma** | gemma4:e4b | 8K | P2 |

### 3.2 模型兼容性测试

```python
# 兼容性矩阵测试
test_matrix = [
    # (job_model, slot_model, expected_score)
    ("qwen2.5:7b", "qwen2.5:7b", 1.0),      # EXACT
    ("qwen3:8b", "qwen2.5:7b", 0.8),         # FAMILY (version downgrade OK)
    ("qwen2.5:7b", "qwen3:8b", 0.8),         # FAMILY (version upgrade OK)
    ("llama3:8b", "qwen2.5:7b", 0.0),         # CROSS_FAMILY (INVALID)
]
```

### 3.3 模型性能基准

| 模型 | 平均延迟 | Tokens/sec | 内存占用 |
|------|----------|------------|----------|
| qwen2.5:7b | ~200ms | ~150 | ~4GB |
| qwen3:8b | ~300ms | ~120 | ~5GB |
| llama3:8b | ~250ms | ~130 | ~5GB |
| gemma4:e4b | ~150ms | ~180 | ~3GB |

---

## 四、Job 类型测试

### 4.1 Job 分类

| Job 类型 | 输入长度 | 输出长度 | 复杂度 |
|----------|----------|----------|--------|
| **Simple** | < 100 tokens | < 100 tokens | 低 |
| **Medium** | 100-500 tokens | 100-500 tokens | 中 |
| **Long** | 500-2000 tokens | 500-2000 tokens | 高 |
| **Streaming** | 任意 | 任意 | 中 |

### 4.2 Job 请求模板

```python
# Simple Job
simple_job = {
    "model": "qwen2.5:7b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50,
}

# Medium Job
medium_job = {
    "model": "qwen2.5:7b",
    "messages": [{"role": "user", "content": "Explain quantum computing"}],
    "max_tokens": 500,
}

# Long Job
long_job = {
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Write a comprehensive report on AI"}],
    "max_tokens": 2000,
}
```

---

## 五、测试阶段

### Phase 1: 单任务测试 (Single Job)

| 测试编号 | 测试场景 | 网络状态 | 模型 | 预期结果 |
|----------|----------|----------|------|----------|
| T1-01 | 基础推理 | HTTPS | qwen2.5:7b | ✅ 成功 |
| T1-02 | 基础推理 | P2P | qwen2.5:7b | ✅ 成功 |
| T1-03 | 基础推理 | Relay | qwen2.5:7b | ✅ 成功 |
| T1-04 | 长文本输出 | HTTPS | qwen3:8b | ✅ 成功 |
| T1-05 | 模型兼容性 | HTTPS | llama3:8b | ✅ 成功 |
| T1-06 | 网络切换 | P2P→Relay | qwen2.5:7b | ✅ 成功 |
| T1-07 | 超时处理 | Degraded | qwen2.5:7b | ⚠️ 超时 |

### Phase 2: 多任务测试 (Multi-Job)

| 测试编号 | 测试场景 | 并发数 | 网络状态 | 预期结果 |
|----------|----------|--------|----------|----------|
| T2-01 | 2 并发 | 2 | HTTPS | ✅ 成功 |
| T2-02 | 4 并发 | 4 | HTTPS | ✅ 成功 |
| T2-03 | 8 并发 | 8 | HTTPS | ⚠️ 队列 |
| T2-04 | 混合模型 | 4 | HTTPS | ✅ 成功 |
| T2-05 | 混合模型 | 4 | P2P | ✅ 成功 |
| T2-06 | 容量满 | 5 | HTTPS | ⚠️ 部分失败 |
| T2-07 | Pre-Lock 冲突 | 4 | HTTPS | ✅ 正确拒绝 |
| T2-08 | Pre-Lock TTL | 4 | HTTPS | ✅ 超时释放 |

### Phase 3: 网络降级测试

| 测试编号 | 测试场景 | 触发条件 | 预期结果 |
|----------|----------|----------|----------|
| T3-01 | P2P 断开 | 禁用 P2P | 切换到 Relay |
| T3-02 | Relay 断开 | 禁用 Relay | 切换到 HTTPS |
| T3-03 | 全断开 | 禁用全部 | 等待重连 |
| T3-04 | 网络恢复 | 恢复连接 | 自动恢复 |

### Phase 4: 压力测试

| 测试编号 | 测试场景 | 持续时间 | Job 数 | 预期 |
|----------|----------|----------|--------|------|
| T4-01 | 持续负载 | 10 分钟 | 100 | 稳定 |
| T4-02 | 峰值负载 | 1 分钟 | 50 | 无丢失 |
| T4-03 | 容量极限 | 5 分钟 | 溢出 | 正确拒绝 |

---

## 六、测试命令

### 6.1 本地 Ollama 检查

```bash
# 检查 Ollama 状态
curl http://localhost:11434/api/tags

# 检查模型
ollama list

# 拉取测试模型
ollama pull qwen2.5:7b
ollama pull llama3:8b
ollama pull gemma4:e4b
```

### 6.2 运行测试

```bash
# 启动 Ollama
ollama serve

# Phase 1: 单任务测试
pytest tests/test_phase1_single_job.py -v

# Phase 2: 多任务测试
pytest tests/test_phase2_multi_job.py -v

# Phase 3: 网络降级测试
pytest tests/test_phase3_network_degradation.py -v

# Phase 4: 压力测试
pytest tests/test_phase4_stress.py -v

# 全量测试
pytest tests/ -v --tb=short
```

### 6.3 本地 Ollama 测试脚本

```bash
# 测试 Ollama 连接
python tests/scripts/test_ollama_local.py

# 测试不同模型
python tests/scripts/test_models.py --model qwen2.5:7b
python tests/scripts/test_models.py --model llama3:8b

# 网络模拟测试
python tests/scripts/test_network_modes.py --mode p2p
python tests/scripts/test_network_modes.py --mode relay
```

---

## 七、测试数据

### 7.1 测试 Prompt 库

```python
TEST_PROMPTS = {
    "simple": [
        "Hello, how are you?",
        "What is 2+2?",
        "Say hi in Chinese",
    ],
    "medium": [
        "Explain quantum computing in 3 sentences",
        "Write a Python function to sort a list",
        "What are the benefits of exercise?",
    ],
    "long": [
        "Write a comprehensive essay about artificial intelligence",
        "Explain the history of the internet",
        "Describe the water cycle in detail",
    ],
}
```

### 7.2 性能基准数据

```python
PERFORMANCE_BASELINE = {
    "qwen2.5:7b": {
        "avg_latency_ms": 200,
        "tokens_per_second": 150,
        "success_rate": 0.99,
    },
    "qwen3:8b": {
        "avg_latency_ms": 300,
        "tokens_per_second": 120,
        "success_rate": 0.98,
    },
    "llama3:8b": {
        "avg_latency_ms": 250,
        "tokens_per_second": 130,
        "success_rate": 0.98,
    },
}
```

---

## 八、测试报告

### 8.1 报告结构

```markdown
# 测试报告: YYYY-MM-DD

## 执行摘要
- 总测试数: XX
- 通过: XX (XX%)
- 失败: XX (XX%)

## 网络类型分布
| 网络 | 测试数 | 通过率 |
|------|--------|--------|
| HTTPS | XX | XX% |
| P2P | XX | XX% |
| Relay | XX | XX% |

## 模型分布
| 模型 | 测试数 | 通过率 |
|------|--------|--------|
| qwen2.5:7b | XX | XX% |
| llama3:8b | XX | XX% |

## 失败用例分析
...
```

### 8.2 生成报告

```bash
# 生成测试报告
pytest tests/ -v --tb=short --junit-xml=report.xml

# 生成 HTML 报告
pytest tests/ --html=report.html --self-contained-html

# 性能报告
python tests/scripts/generate_perf_report.py
```

---

## 九、CI/CD 集成

### 9.1 GitHub Actions

```yaml
# .github/workflows/test.yml
name: AI Testing

on: [push, pull_request]

jobs:
  test-local-ollama:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Start Ollama
        run: curl -fsSL https://ollama.com/install.sh | sh
      - name: Pull models
        run: |
          ollama serve &
          sleep 5
          ollama pull qwen2.5:7b
          ollama pull llama3:8b
      - name: Run tests
        run: pytest tests/ -v
```

---

## 十、测试检查清单

### 提交前必须通过

- [ ] 本地 Ollama 服务正常运行
- [ ] 所有 Phase 1 单任务测试通过
- [ ] 所有 Phase 2 多任务测试通过
- [ ] 不同模型测试通过
- [ ] 网络降级测试通过
- [ ] Pre-Lock 机制测试通过
- [ ] 性能基准在合理范围内

### 测试覆盖要求

- [ ] 100% 核心模型测试
- [ ] 100% Match Engine 测试
- [ ] 100% Pre-Lock 机制测试
- [ ] 80% 网络场景测试
- [ ] 80% 模型兼容性测试

---

## 附录

### A. 常用命令

```bash
# 查看 Ollama 日志
tail -f ~/.ollama/logs/ollama.log

# 重启 Ollama
pkill ollama && ollama serve

# 清理 Ollama 模型缓存
ollama rm <model_name>
```

### B. 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 单步执行
pytest tests/test_phase1.py -v -s --pdb
```

---

**最后更新**: 2026-04-13
