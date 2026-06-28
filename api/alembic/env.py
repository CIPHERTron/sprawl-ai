"""
Alembic env.py — async-aware configuration for asyncpg.

We use SQLAlchemy's `conn.run_sync` bridge so that Alembic's synchronous migration
operations work against an async asyncpg connection. No psycopg2 required.

DATABASE_URL must be in asyncpg form:
    postgresql+asyncpg://user:pass@host:port/db
"""
import asyncio
import os
import sys
from logging.config import fileConfig

# Ensure the monorepo root (/app) is on sys.path so `api` and `shared` are importable.
# __file__ = /app/api/alembic/env.py → two levels up = /app
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Import all models so Base.metadata is fully populated for autogenerate
import api.db.models  # noqa: F401
from api.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Prefer the DATABASE_URL environment variable; fall back to alembic.ini
_db_url: str = os.environ.get(
    "DATABASE_URL",
    config.get_main_option("sqlalchemy.url", "postgresql+asyncpg://sprawl:changeme@postgres:5432/sprawl"),
)


def run_migrations_offline() -> None:
    """Emit SQL to stdout (used with --sql flag). No DB connection required."""
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_db_url, poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
