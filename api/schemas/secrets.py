"""
Response schemas for secrets, findings, and blast-radius graph.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SecretOut(BaseModel):
    id: UUID
    type: str
    provider: str | None
    health: str
    environment: str
    exposure_status: str
    severity_score: int | None
    severity_bucket: str | None
    rotatable: bool
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}


class GraphNodeOut(BaseModel):
    id: UUID
    kind: str
    label: str
    environment: str
    attrs: dict

    model_config = {"from_attributes": True}


class GraphEdgeOut(BaseModel):
    id: UUID
    src_node_id: UUID
    dst_node_id: UUID
    kind: str
    confidence: str
    attrs: dict

    model_config = {"from_attributes": True}


class InvestigationCoverage(BaseModel):
    known_consumers: int = 0
    unknown_consumers: int = 0
    confidence: str = "low"


class BlastRadiusOut(BaseModel):
    secret: SecretOut
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    coverage: InvestigationCoverage | None = None
