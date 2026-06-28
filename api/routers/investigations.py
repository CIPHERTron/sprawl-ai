"""
/workspaces/{workspace_id}/investigations — investigation list + detail.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.db.session import get_db
from api.schemas.common import ok, page

router = APIRouter(
    prefix="/workspaces/{workspace_id}/investigations",
    tags=["investigations"],
)


@router.get("")
async def list_investigations(
    workspace_id: UUID,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List investigations for a workspace, newest first."""
    result = await db.execute(
        text("""
            SELECT
                i.id,
                i.secret_id,
                i.status,
                i.coverage,
                i.trace_id,
                i.started_at,
                i.finished_at,
                s.type  AS secret_type,
                s.severity_score,
                s.severity_bucket
            FROM investigations i
            JOIN secrets s ON s.id = i.secret_id
            WHERE i.workspace_id = :workspace_id
            ORDER BY i.started_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"workspace_id": str(workspace_id), "limit": limit, "offset": offset},
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM investigations WHERE workspace_id = :workspace_id"),
        {"workspace_id": str(workspace_id)},
    )
    total = count_result.scalar_one()

    items = [_row_to_dict(r) for r in rows]
    return page(data=items, total=total, limit=limit, offset=offset)


@router.get("/{investigation_id}")
async def get_investigation(
    workspace_id: UUID,
    investigation_id: UUID,
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get a single investigation with graph node + edge counts and severity."""
    result = await db.execute(
        text("""
            SELECT
                i.id,
                i.secret_id,
                i.status,
                i.coverage,
                i.trace_id,
                i.started_at,
                i.finished_at,
                s.type  AS secret_type,
                s.environment,
                s.severity_score,
                s.severity_bucket
            FROM investigations i
            JOIN secrets s ON s.id = i.secret_id
            WHERE i.id = :investigation_id
              AND i.workspace_id = :workspace_id
            LIMIT 1
        """),
        {
            "investigation_id": str(investigation_id),
            "workspace_id": str(workspace_id),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="investigation_not_found"
        )

    data = _row_to_dict(row)

    # Attach node + edge counts (keyed by secret_id — no investigation_id FK in those tables)
    counts = await db.execute(
        text("""
            SELECT
                (SELECT COUNT(*) FROM graph_nodes WHERE secret_id = :sid) AS node_count,
                (SELECT COUNT(*) FROM graph_edges WHERE secret_id = :sid) AS edge_count
        """),
        {"sid": data["secret_id"]},
    )
    count_row = counts.one()
    data["node_count"] = count_row[0]
    data["edge_count"] = count_row[1]

    # Attach latest severity for this secret (severities are keyed by secret_id)
    sev = await db.execute(
        text("""
            SELECT score, factors, explanation
            FROM severities
            WHERE secret_id = (
                SELECT secret_id FROM investigations WHERE id = :iid LIMIT 1
            )
            ORDER BY computed_at DESC
            LIMIT 1
        """),
        {"iid": str(investigation_id)},
    )
    sev_row = sev.mappings().one_or_none()
    if sev_row:
        data["severity"] = {
            "score": sev_row["score"],
            "bucket": data.get("severity_bucket"),
            "factors": sev_row["factors"],
            "explanation": sev_row["explanation"],
        }
    else:
        data["severity"] = None

    return ok(data)


def _row_to_dict(row) -> dict:
    return {
        "id": str(row["id"]),
        "secret_id": str(row["secret_id"]),
        "status": str(row["status"]),
        "coverage": row["coverage"],
        "trace_id": row["trace_id"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "secret_type": row.get("secret_type"),
        "severity_score": row.get("severity_score"),
        "severity_bucket": row.get("severity_bucket"),
    }
