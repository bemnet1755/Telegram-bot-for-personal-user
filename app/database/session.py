"""Async engine + session factory.

The bot runs against PostgreSQL via ``asyncpg``. Tests can point the same
code at an in-memory or file-based SQLite database by overriding the DSN,
which keeps the accounting tests fast and dependency-free.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config.settings import get_settings
from app.database.models import Base


class Database:
    """Holds the engine and session factory for the running application."""

    engine: Optional[AsyncEngine] = None
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @classmethod
    def configure(cls, database_url: Optional[str] = None) -> None:
        """Create (or replace) the engine. Pass a DSN to override (tests)."""
        if database_url is None:
            database_url = get_settings().database_url

        connect_args = {}
        # SQLite in-memory databases need a single shared connection.
        if database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}

        pool_kwargs = {}
        if database_url.startswith("sqlite") and database_url in (
            "sqlite+aiosqlite://",
            "sqlite+aiosqlite:///:memory:",
        ):
            pool_kwargs["poolclass"] = StaticPool

        cls.engine = create_async_engine(database_url, echo=False, **pool_kwargs,
                                         connect_args=connect_args)
        cls.session_factory = async_sessionmaker(cls.engine, expire_on_commit=False)

    @classmethod
    def session(cls) -> AsyncSession:
        if cls.session_factory is None:
            raise RuntimeError("Database not configured; call Database.configure()")
        return cls.session_factory()

    @classmethod
    @asynccontextmanager
    async def session_scope(cls) -> AsyncGenerator[AsyncSession, None]:
        """Context manager: one session per operation, always closed.

        Handlers use ``async with Database.session_scope() as session:`` so
        sessions are released even on errors.
        """
        session = cls.session()
        try:
            yield session
        finally:
            await session.close()

    @classmethod
    async def create_schema(cls) -> None:
        """Create all tables (used by tests). Relies on the shared Base metadata."""
        if cls.engine is None:
            raise RuntimeError("Database not configured; call Database.configure()")
        async with cls.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @classmethod
    async def drop_schema(cls) -> None:
        if cls.engine is None:
            raise RuntimeError("Database not configured; call Database.configure()")
        async with cls.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @classmethod
    async def dispose(cls) -> None:
        if cls.engine is not None:
            await cls.engine.dispose()


def sync_database_url() -> str:
    """Return a sync DSN for Alembic (psycopg2 for Postgres, plain SQLite)."""
    raw = os.environ.get("DATABASE_URL") or get_settings().database_url
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if raw.startswith("sqlite+aiosqlite"):
        return raw.replace("sqlite+aiosqlite", "sqlite", 1)
    return raw
