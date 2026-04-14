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
            "model_requirement": "llama3-8b",
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
        """测试无效模型（实际系统不限制模型，任何字符串都可接受）"""
        response = client.post("/api/v1/jobs", json={
            "model_requirement": "gpt-4",  # 不支持的模型
            "input_tokens": 2048,
            "output_tokens_limit": 1024,
            "max_latency": 5000,
            "bid_price": 0.35,
        })
        
        # 系统不限制模型，任何字符串都可接受
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
    
    def test_create_job_invalid_bid_price(self, client):
        """测试无效 bid_price"""
        response = client.post("/api/v1/jobs", json={
            "model_requirement": "llama3-8b",
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
    
    def test_register_node_requires_valid_user(self, client):
        """测试注册节点需要有效用户"""
        response = client.post("/api/v1/nodes", json={
            "user_id": "invalid-uuid",  # 无效 UUID
            "gpu_type": "RTX4090",
            "vram_gb": 24,
            "gpu_qty": 1,
            "os_name": "Linux",
            "os_version": "Ubuntu 22.04",
            "runtime": "ollama",
            "model": "llama3-8b",
            "model_support": ["llama3-8b"],
            "ask_price": 0.30,
            "avg_latency": 3500,
            "region": "us-west",
        })
        
        # 应该返回 403，因为用户无效
        assert response.status_code == 403
    
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


class TestMatchingIntegration:
    """测试撮合集成"""
    
    def test_job_matching_flow_requires_auth(self, client):
        """测试 Job 撮合流程需要用户认证"""
        # 1. 注册节点需要有效用户（使用无效 UUID）
        node_response = client.post("/api/v1/nodes", json={
            "user_id": "invalid-uuid",
            "gpu_type": "RTX4090",
            "vram_gb": 24,
            "gpu_qty": 1,
            "os_name": "Linux",
            "os_version": "Ubuntu 22.04",
            "runtime": "ollama",
            "model": "llama3-8b",
            "model_support": ["llama3-8b"],
            "ask_price": 0.30,
            "avg_latency": 3500,
            "region": "us-west",
        })
        
        # 应该返回 403，因为用户无效
        assert node_response.status_code == 403
