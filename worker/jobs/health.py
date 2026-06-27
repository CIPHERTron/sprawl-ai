import structlog

logger = structlog.get_logger(__name__)


async def health_check(ctx: dict) -> dict:
    """Lightweight job to verify the worker queue is processing."""
    logger.info("worker.health_check")
    return {"status": "ok", "service": "worker"}
