#!/usr/bin/env python3
"""
Database Initialization Script
Run this script to initialize the database
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import engine, Base
from src.models.db_models import (
    JobDB, NodeDB, MatchDB, EscrowDB,
    StakeRecordDB, DisputeDB, AppealDB
)


def init_database():
    """Initialize database tables"""
    print("Creating database tables...")
    
    Base.metadata.create_all(bind=engine)
    
    print("Database tables created successfully!")
    print("\nTables:")
    for table in Base.metadata.tables:
        print(f"  - {table}")


def reset_database():
    """Reset database (drop and recreate all tables)"""
    print("WARNING: This will delete all data!")
    confirm = input("Type 'yes' to confirm: ")
    
    if confirm.lower() != "yes":
        print("Aborted.")
        return
    
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    
    print("Recreating tables...")
    init_database()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        reset_database()
    else:
        init_database()
