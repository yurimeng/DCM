"""
DCM - Decentralized Compute Market
Main Application Entry
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import settings
from .api import jobs_router, nodes_router, users_router, internal_router, disputes_router, wallet_router, p2p_router, quic_router, relay_router, core_router, scaler_router, worker_pool_router
from .database import init_db, SessionLocal


def _create_test_users():
    """
    Create test users for development
    创建测试用户
    
    Test accounts:
    - user1 / 123456
    - user2 / 123456
    - user3 / 123456
    """
    from .models.user import User, AuthProvider, UserRole
    from .repositories import UserRepository
    import uuid
    
    db = SessionLocal()
    try:
        user_repo = UserRepository(db)
        
        test_users = [
            {"email": "user1@example.com", "username": "user1"},
            {"email": "user2@example.com", "username": "user2"},
            {"email": "user3@example.com", "username": "user3"},
        ]
        
        created_count = 0
        for test_user in test_users:
            # Check if user exists
            existing = user_repo.get_by_email(test_user["email"])
            if existing:
                print(f"  Test user {test_user['username']} already exists")
                continue
            
            # Create user
            user = User(
                user_id=str(uuid.uuid4()),
                auth_provider=AuthProvider.EMAIL,
                email=test_user["email"],
                username=test_user["username"],
                password_hash=User.hash_password("123456"),
                role=UserRole.USER,
                reputation_score=0.5,
            )
            
            user_repo.create(user)
            created_count += 1
            print(f"  Created test user: {test_user['username']} (password: 123456)")
        
        if created_count > 0:
            print(f"  Created {created_count} test users")
        
    except Exception as e:
        print(f"  Warning: Failed to create test users: {e}")
    finally:
        db.close()


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
    
    # 创建测试用户
    print("Creating test users...")
    _create_test_users()
    
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
                node_id=db_node.node_id,
                gpu_type=db_node.gpu_type,
                vram_gb=db_node.vram_gb,
                gpu_count=db_node.gpu_count,
                # Required: runtime and model
                runtime=db_node.runtime,
                model=db_node.model,
                model_support=json.loads(db_node.model_support) if db_node.model_support else [],
                ask_price=float(db_node.ask_price),
                avg_latency=int(db_node.avg_latency),
                region=db_node.region,
                status=NodeStatus.ONLINE,
            )
            matching_service.register_node(node)
            print(f"  Loaded online node: {db_node.node_id[:8]}...")
        
        # 加载 pending jobs
        pending_jobs = db.query(JobDB).filter(
            JobDB.status == JobStatusDB.PENDING
        ).all()
        
        for db_job in pending_jobs:
            # 处理 model 字段（可能为 None）- 使用 model_requirement
            model_req = db_job.model or "generic"
            job = Job(
                model_requirement=model_req,
                input_tokens=db_job.input_tokens or 100,
                output_tokens_limit=db_job.output_tokens_limit or 512,
                max_latency=db_job.max_latency or 30000,
                bid_price=float(db_job.bid_price) if db_job.bid_price else 0.001,
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
app.include_router(users_router)  # Already has /api/v1/users prefix
app.include_router(internal_router)
app.include_router(disputes_router)
app.include_router(wallet_router)
app.include_router(p2p_router, prefix=settings.api_prefix)
app.include_router(quic_router, prefix=settings.api_prefix)
app.include_router(relay_router, prefix=settings.api_prefix)
app.include_router(core_router, prefix=settings.api_prefix)
app.include_router(scaler_router, prefix=settings.api_prefix)
app.include_router(worker_pool_router, prefix=settings.api_prefix)


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
    from .services.queue import create_queue
    
    # 获取队列统计
    queue = create_queue()
    queue_stats = queue.get_stats()
    queue_type = type(queue).__name__
    
    return {
        "system": {
            "version": settings.version,
            "mvp_mode": settings.mvp_mode,
        },
        "matching": {
            "pending_jobs": matching_service.get_pending_jobs_count(),
            "online_nodes": matching_service.get_online_nodes_count(),
        },
        "queue_stats": {
            "type": queue_type,
            "size": queue_stats.size,
            "max_size": queue_stats.max_size,
            "dead_letter_size": queue_stats.dead_letter_size,
            "usage_percent": queue_stats.usage_percent,
        },
        "config": {
            "platform_fee_rate": settings.platform_fee_rate,
            "layer2_sample_rate": settings.layer2_sample_rate,
            "escrow_buffer": settings.escrow_buffer,
        },
    }
