"""
GitHub source models: GithubInstallation, Repo, Scan.

Scan deduplication (M4):
  - Non-forced scans are unique by (repo_id, type, head_sha) via partial index.
  - Forced scans (explicit POST /repos/{id}/scan) always insert, bypassing dedupe (N2).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from shared.models.enums import ScanStatus

scan_status_enum = sa.Enum(ScanStatus, name="scan_status", create_type=False)


class GithubInstallation(Base):
    __tablename__ = "github_installations"

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
    installation_id: Mapped[int] = mapped_column(
        sa.BigInteger, unique=True, nullable=False
    )
    account_login: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class Repo(Base):
    __tablename__ = "repos"

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
    installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("github_installations.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "full_name", name="uq_repos_workspace_full_name"),
    )


class Scan(Base):
    __tablename__ = "scans"

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
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("repos.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)  # 'history' | 'incremental'
    status: Mapped[ScanStatus] = mapped_column(
        scan_status_enum, nullable=False, server_default="queued"
    )
    # Resolved before insert — non-null enables real deduplication (M4)
    head_sha: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Forced scans (manual rescan) bypass the same-sha dedupe partial index (N2)
    forced: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default="false")
    progress: Mapped[Decimal | None] = mapped_column(sa.Numeric, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Only deduplicate non-forced scans — explicit rescans always allowed (N2)
        sa.Index(
            "scans_dedupe",
            "repo_id", "type", "head_sha",
            unique=True,
            postgresql_where=sa.text("NOT forced"),
        ),
    )
