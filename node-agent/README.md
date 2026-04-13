# DCM Node Agent

> DCM 去中心化算力市场的边缘计算节点代理

## 功能特性

- ✅ **一键安装** - macOS 自动安装脚本
- ✅ **自动注册** - 节点自动注册到 DCM 网络
- ✅ **心跳保活** - 定时心跳保持节点在线
- ✅ **Job 接收** - 从云端接收 AI 推理任务
- ✅ **Ollama 集成** - 支持本地 Ollama 推理引擎
- ✅ **结果上报** - 执行完成后自动返回结果
- 🌐 **多网络协议** - 支持 HTTPS/P2P/Relay 自动切换

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    DCM Node Agent                       │
├─────────────────────────────────────────────────────────┤
│ 1. 注册模块 (Register)                                  │
│ 2. 心跳模块 (Heartbeat)                                │
│ 3. Job 轮询 (Poll)                                     │
│ 4. Runtime Adapter Layer (推理引擎适配)                 │
│ 5. Network Layer (多协议支持)                           │
│ 6. 结果上报 (Result Submit)                            │
└───────────┬─────────────────────────────┬─────────────────┘
            │                             │
      ┌─────┴─────┐              ┌───────┴───────┐
      │  Ollama   │              │  Network      │
      │ (推理)    │              │ HTTPS|P2P|Relay│
      └───────────┘              └───────────────┘
```

## 网络协议支持

| 协议 | 说明 | 状态 |
|------|------|------|
| **HTTPS** | 标准 REST API 轮询 | ✅ 已实现 |
| **P2P** | 点对点通信 (gossipsub) | 🔜 预留 |
| **Relay** | 中继穿透 (circuit relay) | 🔜 预留 |

### 网络降级策略

```
HTTPS → P2P → Relay → OFFLINE
```

当主网络不可用时，Node Agent 自动降级到备用协议。

## 快速开始

### 1. 一键安装

```bash
# 下载并运行安装脚本
curl -fsSL https://raw.githubusercontent.com/yurimeng/DCM/main/node-agent/scripts/install.sh -o install.sh
chmod +x install.sh
./install.sh
```

### 2. 手动安装

```bash
# 克隆项目
git clone https://github.com/yurimeng/DCM.git
cd DCM/node-agent

# 安装依赖
pip3 install -r requirements.txt

# 启动
python3 -m src.node_agent
```

### 3. 管理命令

```bash
# 启动
./start.sh

# 停止
./stop.sh

# 查看状态
./status.sh

# 查看日志
tail -f logs/agent.log
```

## 配置

配置文件: `~/.dcm-node-agent/config.json`

```json
{
    "dcm_url": "https://dcm-api-p00a.onrender.com",
    "model": "qwen2.5:7b",
    "gpu_count": 1,
    "slot_count": 4,
    "worker_count": 2,
    "poll_interval": 3,
    "heartbeat_interval": 30,
    "stake_amount": 200.0,
    "network_enabled": true,
    "p2p_enabled": false,
    "relay_enabled": false
}
```

## 前置要求

- macOS (支持 Apple Silicon 和 Intel)
- Python 3.8+
- Ollama (自动安装或手动安装)

## Ollama 模型

推荐安装以下模型:

```bash
# 安装 Qwen 2.5
ollama pull qwen2.5:7b

# 安装 Gemma
ollama pull gemma:7b

# 查看已安装模型
ollama list
```

## 技术规范

### Invoke 结构 (输入)

```json
{
  "execution_id": "exec_001",
  "job_id": "job_001",
  "slot_id": "slot_001",
  "model": {"name": "qwen2.5:7b", "family": "qwen"},
  "input": {"type": "chat_completion", "messages": [...]},
  "generation": {"max_tokens": 100, "temperature": 0.7},
  "runtime": {"backend": "ollama", "api_style": "openai"},
  "network_type": "https",
  "connection_hints": {}
}
```

### Result 结构 (输出)

```json
{
  "execution_id": "exec_001",
  "job_id": "job_001",
  "status": "completed",
  "output": {"type": "chat_completion", "text": "..."},
  "usage": {"input_tokens": 10, "output_tokens": 50},
  "metrics": {"latency_ms": 1200, "tokens_per_second": 41.6},
  "error": null,
  "return_route": "https",
  "delivery_status": "delivered"
}
```

## 网络状态

| 状态 | 说明 |
|------|------|
| `online` | 正常 HTTPS 连接 |
| `p2p_direct` | P2P 直连 |
| `p2p_relay` | P2P 中继 |
| `degraded` | 降级模式 |
| `offline` | 断开连接 |
| `timeout` | 超时 |

## 许可证

MIT
