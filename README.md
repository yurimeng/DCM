# DCM - Decentralized Compute Market

> A decentralized AI inference marketplace where anyone can buy or sell computing power.
>
> **Version**: v3.2 | **Status**: MVP | **E2E Tests**: ✅ 10/10 Passed

---

## 🎯 Overview

DCM is a **permissionless AI inference marketplace** that enables:
- **Buyers** rent GPU compute at competitive prices
- **Node Operators** monetize idle GPU resources
- **Market Forces** determine fair pricing through open competition

```
┌─────────────────────────────────────────────────────────────────┐
│                         DCM Architecture                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│   │    Buyer     │────▶│     API     │◀────│    Node     │    │
│   │   (User)     │     │   Gateway   │     │  (Provider) │    │
│   └──────────────┘     └──────┬───────┘     └──────────────┘    │
│                                │                                 │
│                    ┌────────────┼────────────┐                   │
│                    │            │            │                   │
│                    ▼            ▼            ▼                   │
│              ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│              │ Matching │ │  Escrow  │ │ Settlement│              │
│              │ Service  │ │ Service  │ │ Service   │              │
│              └──────────┘ └──────────┘ └──────────┘              │
│                    │            │            │                   │
│                    └────────────┼────────────┘                   │
│                                 │                                 │
│                    ┌────────────▼────────────┐                   │
│                    │      NodeStatusStore   │                   │
│                    │   (Real-time Status)    │                   │
│                    └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Quick Start

### 1. Run with Docker

```bash
# Pull and run
docker run -p 8000:8000 ghcr.io/yurimeng/dcm:v3.2

# Or use docker-compose
docker-compose up -d
```

### 2. Run Locally

```bash
# Clone and install
git clone https://github.com/yurimeng/DCM.git
cd DCM

# Start Ollama (required for inference)
ollama serve &
ollama pull qwen2.5:7b

# Run DCM
pip install -r requirements.txt
rm -f dcm.db  # Reset database
python -m uvicorn src.main:app --reload
```

### 3. API Access

- **API**: http://localhost:8000
- **Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health

---

## 🔧 Core Features

### OpenAI Compatible API (v3.2) ✅

```bash
# Create a job using OpenAI-compatible format
curl -X POST http://localhost:8000/api/v1/jobs/openai \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:7b",
    "messages": [{"role": "user", "content": "What is 1+1?"}],
    "max_tokens": 100,
    "temperature": 0.7
  }'
```

### Node Registration
```bash
# Register as a compute provider
curl -X POST http://localhost:8000/api/v1/nodes \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "your-user-id",
    "runtime": {
      "type": "ollama",
      "loaded_models": ["qwen2.5:7b"]
    },
    "pricing": {
      "ask_price": 0.000001
    },
    "hardware": {
      "gpu_type": "RTX",
      "gpu_count": 1
    }
  }'
```

---

## 🏗️ Architecture

### Components (v3.2)

| Component | Status | Description |
|-----------|--------|-------------|
| **API Gateway** | ✅ | FastAPI-based REST API |
| **Matching Service** | ✅ | Job-Node matching engine |
| **NodeStatusStore** | ✅ | Real-time node health tracking |
| **Job Queue** | ✅ | Priority queue with retry logic |
| **Escrow Service** | ✅ | Payment holding and settlement |
| **OpenAI API** | ✅ | OpenAI Chat Completions compatible |
| **Verification Service** | ⚠️ | Basic validation only |

### Matching Flow

```
Job Created → Price Check → Model Match → Latency Check → Capacity Check
     │            │            │            │              │
     ▼            ▼            ▼            ▼              ▼
  Escrow    bid ≥ ask    node has    latency ≤    queue has
  Locked    ✓/✗         model ✓/✗   max ✓/✗     space ✓/✗
                                                     │
                                                     ▼
                                            Match Created
                                                     │
                                                     ▼
                                         Node Poll → Execute → Result
```

---

## 📊 API Reference

### Job API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/jobs/openai` | Create job (OpenAI compatible) ✅ |
| `POST` | `/api/v1/jobs` | Create job (DCM format) |
| `GET` | `/api/v1/jobs/{id}` | Get job status |
| `POST` | `/api/v1/jobs/{id}/submit-result` | Submit result |

### Node API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/nodes` | Register node |
| `POST` | `/api/v1/nodes/{id}/online` | Node goes online |
| `POST` | `/api/v1/nodes/{id}/live_status` | Report live status |
| `POST` | `/api/v1/nodes/{id}/poll` | Poll for jobs |
| `POST` | `/api/v1/nodes/{id}/execute` | Execute job |

### User API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/users/register` | Register user |
| `POST` | `/api/v1/users/login` | Login |

---

## 🧪 Testing

### E2E Test Results (v3.2) ✅

```bash
# Run E2E tests
python scripts/test_e2e_10_jobs.py

# Results: 10/10 passed
============================================================
E2E Test - 10 Jobs Complete Flow
============================================================
DCM: http://localhost:8000
Ollama: http://localhost:11434
Model: qwen2.5:7b
============================================================

[TEST 1/10] Math     ✅ Latency: 1447ms, Tokens: 8
[TEST 2/10] Joke     ✅ Latency: 568ms, Tokens: 24
[TEST 3/10] Capital  ✅ Latency: 281ms, Tokens: 8
[TEST 4/10] Definition ✅ Latency: 986ms, Tokens: 50
[TEST 5/10] List     ✅ Latency: 1018ms, Tokens: 50
[TEST 6/10] Color    ✅ Latency: 791ms, Tokens: 37
[TEST 7/10] Science  ✅ Latency: 1016ms, Tokens: 50
[TEST 8/10] History  ✅ Latency: 1025ms, Tokens: 50
[TEST 9/10] Math2    ✅ Latency: 388ms, Tokens: 14
[TEST 10/10] Greeting ✅ Latency: 211ms, Tokens: 4

============================================================
Passed: 10/10
🎉 All tests passed!
```

### Other Tests

```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/test_phase1.py
pytest tests/test_phase2.py
pytest tests/test_phase3_e2e.py

# JobCreate format tests
python scripts/test_job_create_10.py  # 10/10 passed
```

---

## 💰 Economics

### Pricing Model

```
All prices in USDC per token

Default bid_price: 0.000001 (1 USDC/1M tokens)
Default max_latency: 30000ms
```

### Fee Distribution

| Party | Share |
|-------|-------|
| Node Operator | 95% |
| Platform | 5% |

---

## 🔐 Security

### Verification Layers

| Layer | Trigger | Purpose |
|-------|---------|---------|
| **Layer 1** | Every job | Basic validation |
| **Layer 2** | 10% random | Deep verification |

---

## 📈 Version History

| Version | Date | Status | Notes |
|---------|------|--------|-------|
| 3.0 | 2026-04-12 | ✅ | Basic Match Engine |
| 3.1 | 2026-04-13 | ✅ | Pre-Lock, Slot abstraction |
| **3.2** | 2026-04-15 | **✅ MVP** | OpenAI API, NodeStatusStore, E2E passed |

---

## 📝 Documentation

- [Architecture](DCM/docs/DCM-v3.2-Architecture.md)
- [Match Engine](DCM/Match Engine v3.2 架构.md)
- [OpenAI API](CreateJob API.md)
- [Function Index](DCM/Function/Function 模块索引.md)

---

## 🤝 Contributing

> **v3.2 MVP Status**: This version is feature-frozen. Only bug fixes will be accepted.

1. Fork the repository
2. Create a bugfix branch (`git checkout -b fix/bug-description`)
3. Commit changes (`git commit -m 'Fix: bug description'`)
4. Push to branch (`git push origin fix/bug-description`)
5. Open a Pull Request

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🔗 Links

- [GitHub Repository](https://github.com/yurimeng/DCM)
- [Documentation](https://docs.dcm.market)
- [Discord Community](https://discord.gg/dcm)
- [Twitter](https://twitter.com/dcm_market)

---

## 🙏 Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [Ollama](https://ollama.ai/)
