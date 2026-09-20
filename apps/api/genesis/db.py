"""Database engine and session management.

Deliberately synchronous: the orchestrator runs in a background thread and
uses plain sessions, which keeps the research loop free of async-DB friction.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

logger = logging.getLogger(__name__)

_settings = get_settings()

# SQLite needs check_same_thread=False because the orchestrator thread and the
# request threads share the engine. Postgres needs pre-ping for Railway's
# connection recycling.
_connect_args: dict[str, object] = {}
_engine_kwargs: dict[str, object] = {"pool_pre_ping": True, "future": True}

if _settings.is_sqlite:
    _connect_args["check_same_thread"] = False
    # Serialize writers rather than fail fast on concurrent access.
    _connect_args["timeout"] = 30

engine = create_engine(_settings.database_url, connect_args=_connect_args, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they do not exist. Enough for a hackathon; no Alembic."""
    Base.metadata.create_all(bind=engine)
    if _settings.is_sqlite:
        # WAL lets the orchestrator write while HTTP readers read.
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.commit()
    logger.info("database ready (%s)", "sqlite" if _settings.is_sqlite else "postgres")


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for the orchestrator thread."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
