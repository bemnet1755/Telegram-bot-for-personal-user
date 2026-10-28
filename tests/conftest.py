"""Shared fixtures for the test suite.

Uses an in-memory SQLite database via aiosqlite so tests are self-contained
and run without a running PostgreSQL instance.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.models import Base
from app.database.session import Database


# ---------------------------------------------------------------------------
# Engine / session fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def engine():
    """In-memory SQLite engine, freshly created per test."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(engine):
    """Session factory tied to the in-memory engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="function")
async def db(session_factory) -> AsyncSession:
    """Single open session for use within a test (not auto-committed)."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function", autouse=True)
async def configure_database(engine, session_factory):
    """Point the global Database class at the in-memory engine for each test."""
    Database.engine = engine
    Database.session_factory = session_factory
    yield
    # Teardown is handled by the `engine` fixture (drop_all + dispose).
