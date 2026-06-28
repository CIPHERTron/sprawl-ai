"""
Rotation & RotationStep models — deterministic state machine (§8.5, §5.3).

Key invariants:
  - plan IS NOT NULL for all states except 'proposed' and 'plan_failed' (N1).
  - At most one active rotation per secret (one_active_rotation partial index).
  - Steps are idempotent: unique by (rotation_id, idx).
  - workspace_id on rotation_steps for parity with all other business tables (N4).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from shared.models.enums import RotationStatus, StepKind, StepStatus

rotation_status_enum = sa.Enum(
    RotationStatus, name="rotation_status", create_type=False
)
step_kind_enum = sa.Enum(StepKind, name="step_kind", create_type=False)
step_status_enum = sa.Enum(StepStatus, name="step_status", create_type=False)

# Terminal states that release the one_active_rotation lock
_TERMINAL_STATUSES = (
    "completed", "rolled_back", "rejected", "rollback_failed", "abandoned", "plan_failed"
)
_ACTIVE_WHERE = sa.text(
    "status NOT IN ('completed','rolled_back','rejected','rollback_failed','abandoned','plan_failed')"
)


class Rotation(Base):
    __tablename__ = "rotations"

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
    status: Mapped[RotationStatus] = mapped_column(
        rotation_status_enum, nullable=False, server_default="proposed"
    )
    # NULL during pre-plan phase ('proposed'); set at 'pending_approval' (N1 / H1)
    plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Why planning failed — populated for 'plan_failed' (N1)
    plan_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    coverage: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    new_secret_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Plan TTL — engine moves to 'needs_replan' if elapsed before approval (C6)
    plan_expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        # N1: plan required for every state except the two pre-plan states
        sa.CheckConstraint(
            "plan IS NOT NULL OR status IN ('proposed','plan_failed')",
            name="plan_present_when_actionable",
        ),
        # At most one active (non-terminal) rotation per secret
        sa.Index(
            "one_active_rotation",
            "secret_id",
            unique=True,
            postgresql_where=_ACTIVE_WHERE,
        ),
    )


class RotationStep(Base):
    __tablename__ = "rotation_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    # N4: workspace_id on all business tables for consistent row ownership
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    rotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("rotations.id", ondelete="CASCADE"),
        nullable=False,
    )
    idx: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    kind: Mapped[StepKind] = mapped_column(step_kind_enum, nullable=False)
    # ConsumerRef | StoreRef (no secret value)
    target: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # How to undo this step (compensation)
    compensation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default="false"
    )
    status: Mapped[StepStatus] = mapped_column(
        step_status_enum, nullable=False, server_default="pending"
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        # Idempotency: engine identifies a step by (rotation_id, idx)
        sa.UniqueConstraint("rotation_id", "idx", name="uq_rotation_steps_rotation_idx"),
    )
