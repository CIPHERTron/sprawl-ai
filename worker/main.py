"""
Sprawl AI — Worker service entry point (arq).

Responsibilities (§5.1):
- All background + agent work: history scans, detection, LangGraph agent runtime,
  rotation state-machine steps.
- LangGraph runtime runs here (never in api).
- Reads creds from Vault via AppRole; only this service + api touch Postgres/Vault.
"""
from arq import cron
from arq.connections import RedisSettings

from worker.jobs import JOB_REGISTRY


async def startup(ctx: dict) -> None:
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("worker.startup")


async def shutdown(ctx: dict) -> None:
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("worker.shutdown")


class WorkerSettings:
    """arq worker configuration."""
    functions = JOB_REGISTRY
    on_startup = startup
    on_shutdown = shutdown

    # Populated from env in M2+ (REDIS_URL)
    redis_settings = RedisSettings(host="redis", port=6379)

    job_timeout = 300          # 5 min default; rotation steps override per-job
    max_tries = 3
    keep_result = 3600         # keep job results 1 hour
