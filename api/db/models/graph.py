"""
Blast-radius graph models: GraphNode, GraphEdge, Severity.

Severity history is stored per computation; latest score/bucket is denormalized
onto the Secret row for fast sorting/filtering.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.types import confidence_enum, edge_kind_enum, environment_enum, node_kind_enum
from shared.models.enums import Confidence, EdgeKind, Environment, NodeKind


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    secret_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("secrets.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[NodeKind] = mapped_column(node_kind_enum, nullable=False)
    label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    environment: Mapped[Environment] = mapped_column(
        environment_enum, nullable=False, server_default="unknown"
    )
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.Index("ix_graph_nodes_secret_id", "secret_id"),
    )


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    secret_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("secrets.id", ondelete="CASCADE"),
        nullable=False,
    )
    src_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    dst_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[EdgeKind] = mapped_column(edge_kind_enum, nullable=False)
    confidence: Mapped[Confidence] = mapped_column(
        confidence_enum, nullable=False, server_default="medium"
    )
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    __table_args__ = (
        sa.Index("ix_graph_edges_secret_id", "secret_id"),
        sa.Index("ix_graph_edges_src_node_id", "src_node_id"),
    )


class Severity(Base):
    __tablename__ = "severities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    secret_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("secrets.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Deterministic score 0..100 (T1)
    score: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # {scope, environment, exposure} breakdown
    factors: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # LLM-generated natural-language explanation (non-authoritative)
    explanation: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.Index(
            "ix_severities_secret_computed",
            "secret_id",
            sa.text("computed_at DESC"),
        ),
    )
