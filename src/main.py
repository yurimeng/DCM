"""
DCM - Decentralized Compute Market
Main Application Entry
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import settings
from .api import jobs_router, nodes_router, internal_router, disputes_router, wallet_router, p2p_router
from .database import init_db, SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print(f"DCM v{settings.version} starting...")
    print(f"MVP Mode: {settings.mvp_mode}")
    
    # 初始化数据库
    print("Initializing database...")
    init_db()
    print("Database initialized.")
    
    # 从数据库加载状态到内存
    _load_matching_state()
    
    yield
    
    # 关闭时
    print("DCM shutting down...")


def _load_matching_state():
    """从数据库加载撮合状态到内存"""
    from .models import Node, Job, JobStatus, NodeStatus
    from .models.db_models import JobDB, NodeDB, JobStatusDB, NodeStatusDB
    from .services import matching_service
    from .core.wallet import wallet_service
    import json
    
    db = SessionLocal()
    try:
        # 加载 online nodes
        online_nodes = db.query(NodeDB).filter(
            NodeDB.status == NodeStatusDB.ONLINE
        ).all()
        
        for db_node in online_nodes:
            node = Node(
                gpu_type=db_node.gpu_type,
                vram_gb=db_node.vram_gb,
                model_support=json.loads(db_node.model_support),
                ask_price=float(db_node.ask_price),
                avg_latency=int(db_node.avg_latency),
                region=db_node.region,
            )
            node.node_id = db_node.node_id
            node.status = NodeStatus.ONLINE
            matching_service.register_node(node)
            print(f"  Loaded online node: {db_node.node_id[:8]}...")
        
        # 加载 pending jobs
        pending_jobs = db.query(JobDB).filter(
            JobDB.status == JobStatusDB.PENDING
        ).all()
        
        for db_job in pending_jobs:
            job = Job(
                model=db_job.model,
                input_tokens=db_job.input_tokens,
                output_tokens_limit=db_job.output_tokens_limit,
                max_latency=db_job.max_latency,
                bid_price=float(db_job.bid_price),
            )
            job.job_id = db_job.job_id
            job.status = JobStatus.PENDING
            matching_service.add_job(job)
            print(f"  Loaded pending job: {db_job.job_id[:8]}...")
        
        print(f"Matching state loaded: {len(online_nodes)} nodes, {len(pending_jobs)} jobs")
        
        # 初始化钱包服务（TD-004：从数据库加载）
        wallet_service._db_session = db
        wallet_service.initialize_test_accounts()
        print("Wallet state loaded from database.")
        
    finally:
        db.close()


app = FastAPI(
    title="DCM - Decentralized Compute Market",
    version=settings.version,
    description="""
## 去中心化 AI 推理市场

构建全球去中心化 AI 推理市场，使任何人都可以出售或购买算力。

### 当前阶段
MVP（验证期）- 验证三个核心假设：
- 技术：Job 完整跑通
- 市场：价格自然形成
- 经济：节点有收益

### 核心约束
- MVP 仅支持 llama3-8b 模型
- 使用 USDC 结算
- Escrow 公式: bid × (input + output) / 1M × 1.1
    """,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(jobs_router, prefix=settings.api_prefix)
app.include_router(nodes_router, prefix=settings.api_prefix)
app.include_router(internal_router)
app.include_router(disputes_router)
app.include_router(wallet_router)
app.include_router(p2p_router, prefix=settings.api_prefix)


@app.get("/")
async def root():
    """健康检查"""
    return {
        "name": settings.project_name,
        "version": settings.version,
        "status": "running",
        "mvp_mode": settings.mvp_mode,
        "model": settings.mvp_model,
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "version": settings.version,
    }


@app.get("/stats")
async def get_stats():
    """获取系统统计"""
    from .services import matching_service
    
    return {
        "system": {
            "version": settings.version,
            "mvp_mode": settings.mvp_mode,
        },
        "matching": {
            "pending_jobs": matching_service.get_pending_jobs_count(),
            "online_nodes": matching_service.get_online_nodes_count(),
        },
        "config": {
            "platform_fee_rate": settings.platform_fee_rate,
            "layer2_sample_rate": settings.layer2_sample_rate,
            "escrow_buffer": settings.escrow_buffer,
        },
    }
