"""
/workspaces/{workspace_id}/audit — audit log read view.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.db.session import get_db
from api.schemas.common import page

router = APIRouter(
    prefix="/workspaces/{workspace_id}/audit",
    tags=["audit"],
)


@router.get("")
async def list_audit_events(
    workspace_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Paginated audit log, newest first."""
    result = await db.execute(
        text("""
            SELECT id, workspace_id, actor, action,
                   target_type, target_id,
                   before, after, hash, created_at
            FROM audit_log
            WHERE workspace_id = :wid
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
        """),
        {"wid": str(workspace_id), "limit": limit, "offset": offset},
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM audit_log WHERE workspace_id = :wid"),
        {"wid": str(workspace_id)},
    )
    total = count_result.scalar_one()

    return page(
        data=[_row_to_dict(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _row_to_dict(row) -> dict:
    return {
        "id": str(row["id"]),
        "workspace_id": str(row["workspace_id"]),
        "actor": row["actor"],
        "action": row["action"],
        "target_type": row.get("target_type"),
        "target_id": row.get("target_id"),
        "before": row.get("before"),
        "after": row.get("after"),
        "hash": row["hash"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }
