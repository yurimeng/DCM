"""
Database Module - SQLAlchemy Setup
来源: PRD 0.2 Section 10.1 & Function/F8
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from config import settings

# 创建引擎
if "sqlite" in settings.database_url:
    # SQLite 特殊配置
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
else:
    engine = create_engine(settings.database_url)

# Session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base
Base = declarative_base()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库"""
    from .models.db_models import JobDB, NodeDB, MatchDB, EscrowDB
    Base.metadata.create_all(bind=engine)
