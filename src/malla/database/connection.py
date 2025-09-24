"""
Database connection management for Meshtastic Mesh Health Web UI.
Uses SQLAlchemy for universal (PostgreSQL, SQLite) support.
"""

import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError
from malla.config import get_config

logger = logging.getLogger(__name__)

def get_database_url():
    # Prefer env override, then YAML config, then fallback local SQLite
    return (
        os.getenv("MALLA_DATABASE_URL")
        or get_config().database_url
        or f"sqlite:///meshtastic_history.db"
    )

DATABASE_URL = get_database_url()
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def get_db_session():
    """Get SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_database():
    """Initialize connection and check tables."""
    try:
        conn = engine.connect()
        # Could run CREATE TABLE or Alembic migration here
        conn.close()
        logger.info(f"Database connection successful: {DATABASE_URL}")
    except SQLAlchemyError as e:
        logger.error(f"Database initialization failed: {e}")