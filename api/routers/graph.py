"""
/workspaces/{workspace_id}/secrets/{secret_id}/graph — blast-radius graph.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.db.models.graph import GraphEdge, GraphNode
from api.db.models.investigation import Investigation
from api.db.models.secret import Secret
from api.db.session import get_db
from api.schemas.common import ok
from api.schemas.secrets import (
    BlastRadiusOut,
    GraphEdgeOut,
    GraphNodeOut,
    InvestigationCoverage,
    SecretOut,
)
from shared.models.enums import InvestigationStatus

router = APIRouter(
    prefix="/workspaces/{workspace_id}/secrets",
    tags=["graph"],
)


@router.get("/{secret_id}/graph")
async def get_blast_radius(
    workspace_id: UUID,
    secret_id: UUID,
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    # Secret
    secret_result = await db.execute(
        select(Secret).where(
            Secret.workspace_id == workspace_id, Secret.id == secret_id
        )
    )
    secret = secret_result.scalar_one_or_none()
    if secret is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="secret_not_found")

    # Graph nodes
    nodes_result = await db.execute(
        select(GraphNode).where(
            GraphNode.workspace_id == workspace_id, GraphNode.secret_id == secret_id
        )
    )
    nodes = nodes_result.scalars().all()

    # Graph edges
    edges_result = await db.execute(
        select(GraphEdge).where(
            GraphEdge.workspace_id == workspace_id, GraphEdge.secret_id == secret_id
        )
    )
    edges = edges_result.scalars().all()

    # Latest completed investigation coverage
    inv_result = await db.execute(
        select(Investigation)
        .where(
            Investigation.workspace_id == workspace_id,
            Investigation.secret_id == secret_id,
            Investigation.status == InvestigationStatus.COMPLETE,
        )
        .order_by(Investigation.finished_at.desc())
        .limit(1)
    )
    investigation = inv_result.scalar_one_or_none()
    coverage = None
    if investigation and investigation.coverage:
        cov = investigation.coverage
        coverage = InvestigationCoverage(
            known_consumers=cov.get("known_consumers", 0),
            unknown_consumers=cov.get("unknown_consumers", 0),
            confidence=cov.get("confidence", "low"),
        )

    out = BlastRadiusOut(
        secret=SecretOut.model_validate(secret),
        nodes=[GraphNodeOut.model_validate(n) for n in nodes],
        edges=[GraphEdgeOut.model_validate(e) for e in edges],
        coverage=coverage,
    )
    return ok(out.model_dump())
