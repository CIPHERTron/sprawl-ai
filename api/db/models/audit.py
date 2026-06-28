"""
Audit log model — append-only, hash-chained for tamper evidence (§8.3).

Security properties:
  - App-level: never UPDATE/DELETE; the DB role has INSERT+SELECT only.
  - Hash chain: sha256(prev_hash || canonical_json(payload)) per workspace.
  - Concurrency: pg_advisory_xact_lock serializes appends per workspace
    so chain never forks (see worker/audit/log.py for the writer).
  - id bigserial gives canonical replay order (per workspace).
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    # Monotonic ordering — bigserial is the canonical chain order
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),  # stored as text UUID for hash-chain key
        sa.ForeignKey("workspaces.id"),  # no ON DELETE CASCADE — audit is permanent
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(sa.Text, nullable=False)  # user UUID | 'system'
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    target_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Hash chain
    prev_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.Index(
            "ix_audit_log_workspace_created",
            "workspace_id",
            sa.text("created_at DESC"),
        ),
        sa.Index("ix_audit_log_target", "target_type", "target_id"),
        # N3: chain replay/verify ordered by id per workspace
        sa.Index("ix_audit_log_workspace_id_ordered", "workspace_id", "id"),
    )
