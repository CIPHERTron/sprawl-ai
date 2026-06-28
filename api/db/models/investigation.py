"""
Investigation model.

At most one in-flight investigation per secret is enforced by the partial unique
index `one_active_investigation` (M5). The investigate_secret job upserts against
this so concurrent triggers collapse to one run (idempotency, HLD H4).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from shared.models.enums import InvestigationStatus

investigation_status_enum = sa.Enum(
    InvestigationStatus, name="investigation_status", create_type=False
)


class Investigation(Base):
    __tablename__ = "investigations"

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
    status: Mapped[InvestigationStatus] = mapped_column(
        investigation_status_enum, nullable=False, server_default="running"
    )
    # Langfuse trace correlation
    trace_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Known/unknown consumers from blast-radius pass
    coverage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Enforce at most one in-flight investigation per secret (M5)
        sa.Index(
            "one_active_investigation",
            "secret_id",
            unique=True,
            postgresql_where=sa.text("status = 'running'"),
        ),
    )
