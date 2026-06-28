"""
Secret & Finding models.

Secret: canonical identity of a leaked credential (fingerprint = hash, never the value).
Finding: a single detection event (one file/line in one commit) pointing to a Secret.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.types import (
    environment_enum,
    exposure_status_enum,
    finding_state_enum,
    secret_health_enum,
    severity_bucket_enum,
)
from shared.models.enums import (
    Environment,
    ExposureStatus,
    FindingState,
    SecretHealth,
    SeverityBucket,
)


class Secret(Base):
    __tablename__ = "secrets"

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
    # Canonical identity hash — NEVER the secret value (C1)
    fingerprint: Mapped[str] = mapped_column(sa.Text, nullable=False)
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)  # 'aws_iam_key', 'stripe', ...
    provider: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Resolved IAM principal — no secret value (C1)
    principal_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Where it's managed (Vault path / SSM path ref)
    store_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    health: Mapped[SecretHealth] = mapped_column(
        secret_health_enum, nullable=False, server_default="unknown"
    )
    environment: Mapped[Environment] = mapped_column(
        environment_enum, nullable=False, server_default="unknown"
    )
    exposure_status: Mapped[ExposureStatus] = mapped_column(
        exposure_status_enum, nullable=False, server_default="unknown"
    )
    severity_score: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    severity_bucket: Mapped[SeverityBucket | None] = mapped_column(
        severity_bucket_enum, nullable=True
    )
    rotatable: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default="false"
    )
    first_seen: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    last_seen: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "workspace_id", "fingerprint", name="uq_secrets_workspace_fingerprint"
        ),
        sa.Index("ix_secrets_workspace_health", "workspace_id", "health"),
        sa.Index(
            "ix_secrets_workspace_severity",
            "workspace_id",
            sa.text("severity_score DESC"),
        ),
    )


class Finding(Base):
    __tablename__ = "findings"

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
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("secrets.id", ondelete="SET NULL"),
        nullable=True,
    )
    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("repos.id", ondelete="CASCADE"),
        nullable=True,
    )
    detector: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default="gitleaks"
    )
    rule_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    line: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    # Hash of the matched value — NEVER the secret itself (C1)
    match_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    state: Mapped[FindingState] = mapped_column(
        finding_state_enum, nullable=False, server_default="new"
    )
    first_seen: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    last_seen: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "workspace_id", "match_hash", "repo_id", "commit_sha", "file_path", "line",
            name="uq_findings_identity",
        ),
        sa.Index("ix_findings_workspace_state", "workspace_id", "state"),
        sa.Index("ix_findings_secret_id", "secret_id"),
    )
