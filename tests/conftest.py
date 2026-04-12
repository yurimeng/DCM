"""
Pytest Configuration and Fixtures
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.models.db_models import (
    JobDB, NodeDB, MatchDB, EscrowDB,
    StakeRecordDB, DisputeDB, AppealDB
)


@pytest.fixture(scope="function")
def db_engine():
    """Create a test database engine"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create a test database session"""
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_job(db_session):
    """Create a sample job in database"""
    job = JobDB(
        job_id="test-job-001",
        model="llama3-8b",
        input_tokens=2048,
        output_tokens_limit=1024,
        max_latency=5000,
        bid_price=0.35,
        status="pending",
    )
    db_session.add(job)
    db_session.commit()
    return job


@pytest.fixture
def sample_node(db_session):
    """Create a sample node in database"""
    node = NodeDB(
        node_id="test-node-001",
        gpu_type="RTX4090",
        vram_gb=24,
        model_support='["llama3-8b"]',
        ask_price=0.30,
        avg_latency=3500,
        region="us-west",
        status="online",
        stake_required=50.0,
    )
    db_session.add(node)
    db_session.commit()
    return node


@pytest.fixture
def sample_stake_record(db_session, sample_node):
    """Create a sample stake record"""
    stake = StakeRecordDB(
        id="stake-test-001",
        node_id=sample_node.node_id,
        amount=50.0,
        tx_hash="0x1234567890abcdef",
        status="active",
    )
    db_session.add(stake)
    db_session.commit()
    return stake
