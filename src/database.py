"""
Database Module - SQLAlchemy Setup
来源: PRD 0.2 Section 10.1 & Function/F8
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from config import settings

# 使用环境变量 DCM_DATABASE_PATH（优先）
# 云端: DCM_DATABASE_PATH=/app/data/dcm.db
# 本地: DCM_DATABASE_PATH (未设置) 使用相对路径 dcm.db
env_db_path = os.environ.get('DCM_DATABASE_PATH')
if env_db_path:
    db_path = env_db_path
else:
    # 检查 settings 中的路径是否有效
    settings_path = getattr(settings, 'database_path', None) or 'dcm.db'
    # 如果路径是 /app 开头，说明是云端默认值，本地应使用相对路径
    if settings_path.startswith('/app'):
        db_path = 'dcm.db'
    else:
        db_path = settings_path

# 如果路径包含 /app（云端），确保目录存在
db_url = f"sqlite:///{db_path}"

# 创建引擎
if "sqlite" in db_url:
    # 确保目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir and not db_dir.startswith('/app'):
        os.makedirs(db_dir, exist_ok=True)
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
