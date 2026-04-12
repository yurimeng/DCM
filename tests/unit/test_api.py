"""
Unit Tests for DCM - API
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.database import Base, get_db


# Test database setup
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def client():
    """Create test client"""
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


class TestHealthEndpoints:
    """测试健康检查端点"""
    
    def test_root(self, client):
        """测试根路径"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "DCM"
        assert data["status"] == "running"
    
    def test_health(self, client):
        """测试健康检查"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    def test_stats(self, client):
        """测试统计端点"""
        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert "matching" in data
        assert "config" in data


class TestJobsAPI:
    """测试 Jobs API"""
    
    def test_create_job(self, client):
        """测试创建 Job"""
        response = client.post("/api/v1/jobs", json={
            "model": "llama3-8b",
            "input_tokens": 2048,
            "output_tokens_limit": 1024,
            "max_latency": 5000,
            "bid_price": 0.35,
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert "escrow_amount" in data
    
    def test_create_job_invalid_model(self, client):
        """测试无效模型"""
        response = client.post("/api/v1/jobs", json={
            "model": "gpt-4",  # 不支持
            "input_tokens": 2048,
            "output_tokens_limit": 1024,
            "max_latency": 5000,
            "bid_price": 0.35,
        })
        
        assert response.status_code == 422  # Validation error
    
    def test_create_job_invalid_bid_price(self, client):
        """测试无效 bid_price"""
        response = client.post("/api/v1/jobs", json={
            "model": "llama3-8b",
            "input_tokens": 2048,
            "output_tokens_limit": 1024,
            "max_latency": 5000,
            "bid_price": 0,  # 必须 > 0
        })
        
        assert response.status_code == 422
    
    def test_get_job_not_found(self, client):
        """测试获取不存在的 Job"""
        response = client.get("/api/v1/jobs/nonexistent-id")
        assert response.status_code == 404
    
    def test_list_jobs(self, client):
        """测试列出 Jobs"""
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
    
    def test_list_jobs_with_status(self, client):
        """测试按状态列出 Jobs"""
        response = client.get("/api/v1/jobs?status=pending")
        assert response.status_code == 200


class TestNodesAPI:
    """测试 Nodes API"""
    
    def test_register_node(self, client):
        """测试注册节点"""
        response = client.post("/api/v1/nodes", json={
            "gpu_type": "RTX4090",
            "vram_gb": 24,  # 24GB = Professional tier
            "model_support": ["llama3-8b"],
            "ask_price": 0.30,
            "avg_latency": 3500,
            "region": "us-west",
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "node_id" in data
        assert data["stake_required"] == 200.0  # Professional tier
        assert data["status"] == "offline"
    
    def test_register_node_invalid_model(self, client):
        """测试不支持的模型"""
        response = client.post("/api/v1/nodes", json={
            "gpu_type": "RTX4090",
            "vram_gb": 24,
            "model_support": ["gpt-4"],  # 不支持
            "ask_price": 0.30,
            "avg_latency": 3500,
            "region": "us-west",
        })
        
        assert response.status_code == 422
    
    def test_get_node_not_found(self, client):
        """测试获取不存在的节点"""
        response = client.get("/api/v1/nodes/nonexistent-id")
        assert response.status_code == 404
    
    def test_list_nodes(self, client):
        """测试列出节点"""
        response = client.get("/api/v1/nodes")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
    
    def test_node_poll_no_job(self, client):
        """测试节点拉取时无 Job"""
        # 先注册节点
        reg_response = client.post("/api/v1/nodes", json={
            "gpu_type": "RTX4090",
            "vram_gb": 24,
            "model_support": ["llama3-8b"],
            "ask_price": 0.30,
            "avg_latency": 3500,
            "region": "us-west",
        })
        
        node_id = reg_response.json()["node_id"]
        
        # 拉取（尚无待处理 Job）
        response = client.post(f"/api/v1/nodes/{node_id}/poll")
        assert response.status_code == 200
        data = response.json()
        assert data["has_job"] is False


class TestMatchingIntegration:
    """测试撮合集成"""
    
    def test_job_matching_flow(self, client):
        """测试 Job 撮合流程"""
        # 1. 注册节点
        node_response = client.post("/api/v1/nodes", json={
            "gpu_type": "RTX4090",
            "vram_gb": 24,
            "model_support": ["llama3-8b"],
            "ask_price": 0.30,
            "avg_latency": 3500,
            "region": "us-west",
        })
        node_id = node_response.json()["node_id"]
        
        # 2. 存款 Stake
        client.post(f"/api/v1/nodes/{node_id}/stake/deposit", params={
            "tx_hash": "0x1234567890abcdef"
        })
        
        # 3. 节点上线
        client.post(f"/api/v1/nodes/{node_id}/online")
        
        # 4. 提交 Job（应该立即撮合）
        job_response = client.post("/api/v1/jobs", json={
            "model": "llama3-8b",
            "input_tokens": 2048,
            "output_tokens_limit": 1024,
            "max_latency": 5000,
            "bid_price": 0.35,
        })
        
        assert job_response.status_code == 200
        # 由于撮合，可能状态变为 matched
        data = job_response.json()
        assert "job_id" in data
        
        # 5. 节点拉取
        poll_response = client.post(f"/api/v1/nodes/{node_id}/poll")
        assert poll_response.status_code == 200
