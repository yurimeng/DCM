"""
Database Module - SQLAlchemy Setup
来源: PRD 0.2 Section 10.1 & Function/F8
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from config import settings

# 检测运行环境
IS_RENDER = os.environ.get('RENDER', None) is not None
IS_CLOUD = IS_RENDER or os.environ.get('DYNO', None) is not None

# 云端路径: /app/data/ (Render 持久化磁盘)
# 本地路径: dcm.db (相对路径)
if IS_CLOUD:
    # 云端: 使用持久化目录
    db_dir = '/app/data'
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, 'dcm.db')
else:
    # 本地: 使用相对路径
    db_path = os.environ.get('DCM_DATABASE_PATH', 'dcm.db')

db_url = f"sqlite:///{db_path}"

# 创建引擎
if "sqlite" in db_url:
    # SQLite 特殊配置
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
else:
    engine = create_engine(db_url)

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
