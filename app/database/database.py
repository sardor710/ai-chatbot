"""Database initialization and async session management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.models import Base

logger = logging.getLogger(__name__)

# Global engine and sessionmaker holders
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(database_url: str = "sqlite+aiosqlite:///data/app.db") -> AsyncEngine:
    """Get or create async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        connect_args = {}
        # If it's a sqlite path, ensure parent folder exists and set timeout
        if "sqlite" in database_url:
            path_part = database_url.split("///")[-1]
            if path_part and not path_part.startswith(":memory:"):
                db_path = Path(path_part)
                db_path.parent.mkdir(parents=True, exist_ok=True)
            connect_args = {"timeout": 30.0}

        _engine = create_async_engine(
            database_url,
            echo=False,
            future=True,
            connect_args=connect_args,
        )

        if "sqlite" in database_url:
            @event.listens_for(_engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
    return _engine


def get_session_factory(
    database_url: str = "sqlite+aiosqlite:///data/app.db",
) -> async_sessionmaker[AsyncSession]:
    """Get or create async session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(database_url)
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def init_db(database_url: str = "sqlite+aiosqlite:///data/app.db") -> None:
    """Initialize database tables."""
    engine = get_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully.")


async def close_db() -> None:
    """Dispose engine connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine closed.")


@asynccontextmanager
async def get_db_session(
    database_url: str = "sqlite+aiosqlite:///data/app.db",
) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async transactional database session context."""
    factory = get_session_factory(database_url)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
