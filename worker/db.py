"""
Async SQLAlchemy session factory for the worker process.

Mirrors api/db/session.py but is owned by the worker package so there is
no cross-package dependency between api and worker.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from worker.config import worker_settings

engine = create_async_engine(
    worker_settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def close_engine() -> None:
    await engine.dispose()
