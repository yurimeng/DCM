# DCM - Decentralized Compute Market

> A decentralized AI inference marketplace where anyone can buy or sell computing power.
>
> **Version**: v3.2 | **Status**: MVP (Production Ready)

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
│                    │      Polygon Amoy       │                   │
│                    │   (Smart Contracts)      │                   │
│                    └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Quick Start

### 1. Run with Docker

```bash
# Pull and run
docker run -p 8000:8000 ghcr.io/yurimeng/dcm:latest

# Or use docker-compose
docker-compose up -d
```

### 2. Run Locally

```bash
# Clone and install
git clone https://github.com/yurimeng/DCM.git
cd DCM
pip install -r requirements.txt

# Run
python -m uvicorn src.main:app --reload
```

### 3. API Access

- **API**: http://localhost:8000
- **Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health

---

## 🔧 Core Features

### Job Submission
```bash
# Create a job (model is optional - system assigns best match)
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "your-user-id",
    "model": "qwen2.5:7b",        // optional
    "prompt": "What is AI?",
    "input_tokens": 10,
    "output_tokens_limit": 100,
    "max_latency": 30000,
    "bid_price": 0.5
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
      "loaded_models": ["qwen2.5:7b", "llama3:8b"]
    },
    "pricing": {
      "ask_price": 0.01,
      "avg_latency_ms": 100
    },
    "hardware": {
      "gpu_type": "H100",
      "vram_gb": 80
    }
  }'
```

---

## 🏗️ Architecture

### Components

| Component | Description |
|-----------|-------------|
| **API Gateway** | FastAPI-based REST API |
| **Matching Service** | Job-Node matching engine |
| **Node Status Store** | Real-time node health tracking |
| **Job Queue** | Priority queue with retry logic |
| **Escrow Service** | Payment holding and settlement |
| **Verification Service** | Result verification (Layer 1/2) |

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
```

---

## 📊 API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/users/register` | Register user |
| `POST` | `/api/v1/jobs` | Create job |
| `GET` | `/api/v1/jobs/{id}` | Get job status |
| `POST` | `/api/v1/nodes` | Register node |
| `POST` | `/api/v1/nodes/{id}/poll` | Poll for jobs |
| `POST` | `/api/v1/nodes/{id}/result` | Submit result |
| `POST` | `/api/v1/nodes/{id}/live_status` | Report live status |

### WebSocket (P2P)

```javascript
// Connect to P2P network
const ws = new WebSocket('ws://localhost:8000/api/v1/p2p/connect');

// Subscribe to jobs
ws.send(JSON.stringify({
  type: 'subscribe',
  channel: 'jobs'
}));
```

---

## 💰 Economics

### Pricing Model

```
Final Cost = Node Ask Price × Output Tokens

Example:
- Node ask_price: 0.01 USDC/1M tokens
- Output tokens: 50
- Cost: 0.01 × 50 = 0.0005 USDC
```

### Fee Distribution

| Party | Share |
|-------|-------|
| Node Operator | 95% |
| Platform | 5% |

### Escrow Flow

1. **Lock**: Bid amount + buffer held on job creation
2. **Settle**: Node payment transferred on completion
3. **Refund**: Excess returned to buyer

---

## 🔐 Security

### Verification Layers

| Layer | Trigger | Purpose |
|-------|---------|---------|
| **Layer 1** | Every job | Basic validation |
| **Layer 2** | 10% random | Deep verification |

### Stake System

Nodes must stake to participate:
- **Personal**: < 4 GPUs → 50 USDC
- **Professional**: 4-7 GPUs → 200 USDC
- **Datacenter**: 8+ GPUs → 1000 USDC

---

## 🚀 Deployment

### Render (Recommended)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

```bash
# Manual deploy
render deploy --service dcm-api
```

### Local Development

```bash
# Start all services
docker-compose up -d

# Run tests
pytest tests/

# Run with coverage
pytest --cov=src tests/
```

---

## 📈 Performance

### Benchmark Results (10min Stress Test)

| Metric | Value |
|--------|-------|
| Jobs Created | 402 |
| Jobs Completed | 93 |
| Completion Rate | 23.13% |
| Avg Latency | ~500ms |

### Scalability

- **Horizontal**: Add more nodes
- **Vertical**: Increase GPU count per node
- **Concurrent**: Increase `max_concurrency` setting

---

## 🧪 Testing

```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/test_phase1.py
pytest tests/test_phase2.py
pytest tests/test_phase3_e2e.py

# Stress test
python test_batch.py

# Local Ollama test
python tests/test_ollama_integration.py
```

---

## 📝 Documentation

- [API Documentation](docs/)
- [Function Specifications](Function/)
- [Match Engine Architecture](docs/Match-Engine-Architecture.md)
- [Changelog](CHANGELOG.md)

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
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
- [Polygon](https://polygon.technology/)
- [Ollama](https://ollama.ai/)
