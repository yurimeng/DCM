"""
DCM - Decentralized Compute Market
Main Application Entry
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import settings
from .api import jobs_router, nodes_router, internal_router, disputes_router
from .database import init_db


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
    
    yield
    
    # 关闭时
    print("DCM shutting down...")


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
