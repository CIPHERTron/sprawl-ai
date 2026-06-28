"""
Sprawl AI — Worker service entry point (arq).

Responsibilities (§5.1):
- All background + agent work: history scans, detection, LangGraph agent runtime,
  rotation state-machine steps.
- LangGraph runtime runs here (never in api).
- Reads creds from Vault via AppRole; only this service + api touch Postgres/Vault.
"""
import structlog
from arq import cron
from arq.connections import RedisSettings

from worker.config import worker_settings
from worker.db import close_engine
from worker.jobs import JOB_REGISTRY
from worker.jobs.sweeper import sweep_demo_workspaces

logger = structlog.get_logger(__name__)


async def startup(ctx: dict) -> None:
    logger.info("worker.startup", environment=worker_settings.environment)


async def shutdown(ctx: dict) -> None:
    await close_engine()
    logger.info("worker.shutdown")


class WorkerSettings:
    """arq worker configuration."""
    functions = JOB_REGISTRY
    on_startup = startup
    on_shutdown = shutdown

    redis_settings = RedisSettings.from_dsn(worker_settings.redis_url)

    job_timeout = 300       # 5 min default; individual jobs can override
    max_tries = 3
    keep_result = 3600      # keep job results 1 hour

    # ── Cron jobs ──────────────────────────────────────────────────────────
    cron_jobs = [
        # Sweep expired demo workspaces every 15 minutes
        cron(sweep_demo_workspaces, minute={0, 15, 30, 45}),
    ]
