"""
Async SQLAlchemy engine and session factory.

Usage in FastAPI dependency:
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with async_session_maker() as session:
            yield session
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.environment == "development",
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with async_session_maker() as session:
        yield session


async def close_engine() -> None:
    """Dispose the engine on application shutdown."""
    await engine.dispose()
