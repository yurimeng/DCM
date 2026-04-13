# DCM - Decentralized Compute Market

> A decentralized AI inference marketplace where anyone can buy or sell computing power.
> 
> **Version**: v3.1 | **Status**: MVP (Validation)

---

## Overview

DCM is building a **global decentralized AI inference marketplace** that enables permissionless participation in GPU compute trading.

### MVP Validation Goals

| Validation Area | Success Criteria |
|-----------------|------------------|
| **Technical** | Complete job execution: Submit → Execute → Result → Settlement |
| **Market** | Price discovery by market forces, not predetermined |
| **Economics** | Node operators retain earnings, buyers pay less than centralized APIs |

---

## Key Features

- **Slot-based Matching**: Efficient resource allocation with Pre-Lock mechanism
- **Model Compatibility**: Support for multiple model families with compatibility scoring
- **Multi-Job Concurrency**: Single slot supports up to 4 concurrent jobs
- **Blockchain Settlement**: USDC escrow and stake management on Polygon
- **P2P Network**: Decentralized communication with QUIC transport
- **Auto-scaling**: Dynamic worker pool management

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        API Layer (FastAPI)                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │   Jobs   │  │  Nodes   │  │  Wallet  │  │ Disputes │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       └────────────┴────────────┴────────────┘            │
│                          │                                 │
│       ┌───────────────────┴───────────────────┐            │
│       │          Core Cluster (F9)            │            │
│       │  ┌──────────┐  ┌──────────┐          │            │
│       │  │ Scaler   │──│  Worker  │          │            │
│       │  │  (F10)   │  │  Pool    │          │            │
│       │  └──────────┘  │  (F11)   │          │            │
│       │                └────┬─────┘          │            │
│       │                     │                │            │
│       └─────────────────────┼────────────────┘            │
│                             │                              │
│       ┌─────────────────────┼─────────────────────┐        │
│       │        Network Layer (F13-F15)           │        │
│       │  ┌────────┐  ┌────────┐  ┌────────┐     │        │
│       │  │  P2P   │──│  QUIC  │──│ Relay  │     │        │
│       │  │ (F13)  │  │ (F14)  │  │ (F15)  │     │        │
│       │  └────────┘  └────────┘  └────────┘     │        │
│       └─────────────────────────────────────────┘        │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                    Service Layer (F1-F7)                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │  Matching  │  │Verification│  │ Settlement │            │
│  │   Engine   │  │  Service   │  │  Service   │            │
│  └────────────┘  └────────────┘  └────────────┘            │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                  Blockchain (Polygon Amoy)                   │
│  ┌────────────┐  ┌────────────┐                            │
│  │   Escrow   │  │   Stake    │                            │
│  │  Contract  │  │  Contract  │                            │
│  └────────────┘  └────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
DCM/
├── src/
│   ├── main.py              # FastAPI application entry
│   ├── config.py            # Configuration settings
│   ├── database.py          # Database initialization
│   │
│   ├── api/                 # API routes
│   │   ├── jobs.py          # Job submission (F1)
│   │   ├── nodes.py         # Node registration (F2)
│   │   ├── disputes.py      # Dispute handling (F7)
│   │   ├── wallet.py        # Wallet operations
│   │   ├── core.py          # Core cluster (F9)
│   │   ├── scaler.py        # Scaler service (F10)
│   │   ├── worker_pool.py   # Worker pool (F11)
│   │   ├── p2p.py           # P2P network (F13)
│   │   ├── quic.py          # QUIC transport (F14)
│   │   ├── relay.py         # Relay service (F15)
│   │   └── internal.py      # Internal APIs
│   │
│   ├── services/            # Business logic (F1-F7)
│   │   ├── match_engine_v2.py    # Match Engine 2.0 (F3)
│   │   ├── order_book.py         # Order Book
│   │   ├── compatibility.py      # Model compatibility
│   │   ├── hard_filter.py        # Hard filter
│   │   ├── scoring.py            # Scoring function
│   │   ├── pre_lock.py           # Pre-Lock mechanism
│   │   ├── verification.py       # Verification service (F5)
│   │   ├── escrow.py             # Escrow service (F6)
│   │   ├── stake.py              # Stake management (F7)
│   │   ├── retry.py              # Retry mechanism (F4)
│   │   └── chain_sync.py         # Blockchain sync
│   │
│   ├── core/                 # Core infrastructure
│   │   ├── cluster/           # Core cluster services
│   │   │   ├── cluster_service.py
│   │   │   ├── scaler_service.py
│   │   │   └── worker_pool.py
│   │   ├── p2p/              # P2P network (F13)
│   │   ├── quic/             # QUIC transport (F14)
│   │   └── relay/            # Relay service (F15)
│   │
│   ├── models/               # Data models
│   ├── agents/               # Node Agent client
│   └── web3/                 # Blockchain integration
│
├── tests/                    # Test suite
│   ├── test_phase1.py        # Phase 1: Core models
│   ├── test_phase2.py        # Phase 2: Core services
│   ├── test_phase3_e2e.py   # Phase 3: E2E tests
│   ├── test_local_comprehensive.py
│   └── test_ollama_integration.py
│
├── contracts/                # Blockchain contracts
│   ├── Escrow.sol
│   └── Stake.sol
│
├── docs/                     # Documentation
├── Function/                 # Function specs
├── Requirement/             # Requirements
└── Architecture/            # Architecture docs
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| API Layer | FastAPI (Python 3.11+) |
| Database | SQLite (MVP) |
| Settlement Chain | Polygon Amoy (USDC) |
| Verification | SHA256 + ROUGE-L |
| Node Communication | WebSocket + HTTP |
| P2P Network | Custom asyncio + QUIC |

---

## Quick Start

### Prerequisites

- Python 3.11+
- SQLite3
- Ollama (for local inference)

### Installation

```bash
# Clone repository
git clone https://github.com/yurimeng/DCM.git
cd DCM

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start Ollama (in another terminal)
ollama serve
ollama pull qwen2.5:7b

# Start DCM API
uvicorn src.main:app --reload --port 8000
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific phases
pytest tests/test_phase1.py -v
pytest tests/test_phase2.py -v
pytest tests/test_phase3_e2e.py -v

# With coverage
pytest tests/ --cov=src --cov-report=html
```

---

## Core Modules

### Match Engine 2.0 (F3)

| Feature | Description |
|---------|-------------|
| Slot Structure | Trading unit with model, capacity, pricing |
| Order Book | Per-model-family buckets |
| Hard Filter | Compatibility + Capacity + Price + Latency |
| Compatibility Matrix | EXACT=1.0, FAMILY=0.8, COMPATIBLE=0.6 |
| Scoring | Price(30%) + Latency(25%) + Load(15%) + Reputation(15%) + Compat(15%) |
| **Pre-Lock** | 5000ms TTL reservation to prevent conflicts |

### Node Agent

| Feature | Description |
|---------|-------------|
| Protocols | WebSocket (primary) + HTTP Polling (fallback) |
| Registration | Auto-generated UUID, local persistence |
| Heartbeat | 30s interval, 60s timeout |
| Multi-Job | Up to 4 concurrent jobs per slot |
| Ollama Integration | v0.1.25+ supported |

---

## Configuration

Key settings in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `mvp_model` | qwen2.5:7b | Supported model |
| `platform_fee_rate` | 0.05 | 5% platform fee |
| `layer2_sample_rate` | 0.1 | 10% verification sampling |
| `heartbeat_timeout_seconds` | 30 | Node timeout threshold |
| `escrow_buffer` | 1.1 | 1.1x escrow multiplier |

---

## API Endpoints

| Module | Endpoint | Method | Description |
|--------|----------|--------|-------------|
| Jobs | `/api/v1/jobs` | POST | Submit a job |
| Jobs | `/api/v1/jobs/{id}` | GET | Get job status |
| Jobs | `/api/v1/jobs/{id}/result` | POST | Submit result |
| Nodes | `/api/v1/nodes/register` | POST | Register node |
| Nodes | `/api/v1/nodes/{id}/poll` | GET | Poll for jobs |
| Nodes | `/api/v1/nodes/{id}/heartbeat` | POST | Send heartbeat |
| Workers | `/api/v1/workers/register` | POST | Register worker |
| Cluster | `/api/v1/cluster/status` | GET | Cluster status |
| Scaler | `/api/v1/scaler/status` | GET | Scaler status |
| P2P | `/api/v1/p2p/status` | GET | P2P network status |

---

## Blockchain Integration

### Contracts

- `Escrow.sol` - USDC escrow for job payments
- `Stake.sol` - Node stake management

### Deployment

```bash
cd contracts
npm install
npx hardhat run scripts/deploy_contracts.js --network polygon_amoy
```

### Environment Variables

```bash
ETH_RPC_URL=https://polygon-amoy.g.alchemy.com/v2/YOUR_KEY
PRIVATE_KEY=your_private_key
USE_BLOCKCHAIN=true
```

---

## Core Design Constraints

| Rule | Description |
|------|-------------|
| DCM-01 | Stake must be in on-chain contract, never in system account |
| DCM-02 | No manual node selection, all matching via Router |
| DCM-03 | Layer 1 verification (SHA256) must be online |
| DCM-04 | Disputes: Freeze without deduction, Buyer not compensated |

---

## Documentation

- **Architecture**: `Architecture/DCM-v3.1-Architecture.md`
- **Match Engine**: `Function/F3-Match-Engine-2.0.md`
- **Node Agent**: `Function/F2-NodeAgent-Spec.md`
- **Full Docs**: Obsidian Vault `YurimengKB/DCM/`

---

## License

MIT License
