"""
Hash-chained audit log for the worker process (mirrors api/audit/log.py).

Uses raw SQL (sqlalchemy text) instead of ORM models since the worker
package does not depend on sprawl-api.

The hash-chain algorithm is identical to the API's implementation:
  hash = sha256(prev_hash || canonical_json(payload))
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, payload: dict) -> str:
    raw = (prev_hash + _canonical_json(payload)).encode()
    return hashlib.sha256(raw).hexdigest()


async def audit(
    db: AsyncSession,
    workspace_id: str,
    actor: str,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> None:
    """
    Append a tamper-evident audit entry.
    Must be called inside an active transaction.
    """
    # Advisory lock to serialise chain writes per workspace
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"audit:{workspace_id}"},
    )

    # Fetch previous hash
    result = await db.execute(
        text(
            "SELECT hash FROM audit_log "
            "WHERE workspace_id = :workspace_id "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"workspace_id": workspace_id},
    )
    row = result.one_or_none()
    prev_hash: str = row[0] if row else ("0" * 64)

    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "actor": actor,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "before": before,
        "after": after,
        "correlation_id": correlation_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    new_hash = _compute_hash(prev_hash, payload)

    await db.execute(
        text("""
            INSERT INTO audit_log
                (workspace_id, actor, action, target_type, target_id,
                 before, after, correlation_id, prev_hash, hash)
            VALUES
                (:workspace_id, :actor, :action, :target_type, :target_id,
                 CAST(:before AS jsonb), CAST(:after AS jsonb), :correlation_id, :prev_hash, :hash)
        """),
        {
            "workspace_id": workspace_id,
            "actor": actor,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "before": json.dumps(before) if before else None,
            "after": json.dumps(after) if after else None,
            "correlation_id": correlation_id,
            "prev_hash": prev_hash,
            "hash": new_hash,
        },
    )
    logger.info("worker.audit.appended", workspace_id=workspace_id, action=action)
