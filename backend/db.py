"""
db.py
-----
Database Engine & Session Management Module.

WHAT THIS FILE DOES:
1. Initializes SQLAlchemy 2.0 database engine (SQLite locally or Postgres in production).
2. Enables WAL (Write-Ahead Logging) and Foreign Key enforcement for fast SQLite operations.
3. Provides `init_db()` to auto-create database tables on startup.
4. Provides `get_db()` dependency generator for FastAPI endpoints.
"""

from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings


# Base class for SQLAlchemy ORM data models
class Base(DeclarativeBase):
    pass


_is_sqlite = settings.database_url.startswith("sqlite")

# Create database engine connection
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

# Enable SQLite performance optimizations (Foreign Keys & Write-Ahead Logging)
if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# Session factory for creating database sessions
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Creates all database tables defined in models.py if they do not exist."""
    import models  # noqa: F401 (Registers ORM models)

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency to yield a database session per HTTP request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
