"""
Demo workspace sweeper — runs every 15 minutes via arq cron.

Deletes all workspaces where kind = 'demo' AND expires_at < now().
ON DELETE CASCADE in the schema cleans up every child row automatically
(secrets, findings, graph_nodes, rotations, audit_log, etc.).

LangGraph checkpoints are library-owned tables with no FK to workspaces,
so we delete them by thread_id pattern: '<workspace_id>:*' (M7 finalizer).
For M3 the demo workspaces don't yet have LangGraph threads, so a simple
CASCADE delete is sufficient.
"""
import structlog
from sqlalchemy import text

from worker.db import async_session_maker

logger = structlog.get_logger(__name__)


async def sweep_demo_workspaces(ctx: dict) -> dict:
    """
    arq job: delete expired demo workspaces.
    Idempotent — safe to re-run at any time.
    """
    async with async_session_maker() as db:
        async with db.begin():
            result = await db.execute(
                text(
                    "DELETE FROM workspaces "
                    "WHERE kind = 'demo' AND expires_at < now() "
                    "RETURNING id"
                )
            )
            deleted_ids = [str(row[0]) for row in result.fetchall()]

    count = len(deleted_ids)
    if count:
        logger.info("sweeper.demo_workspaces_deleted", count=count, ids=deleted_ids)
    else:
        logger.debug("sweeper.no_expired_demo_workspaces")

    return {"deleted": count, "ids": deleted_ids}
