"""
Identity & tenancy models: Workspace, User, Membership.

Every business table carries workspace_id (single-tenant MVP, forward-compatible).
Demo workspaces use kind='demo' with expires_at for TTL GC (§8.2 H4).
No sessions table — stateless JWT (R2).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base
from shared.models.enums import Role, WorkspaceKind

# Postgres-native enum types, defined here for column declarations.
# create_type=False because the migration creates them via raw SQL.
workspace_kind_type = sa.Enum(
    WorkspaceKind, name="workspace_kind", create_type=False
)
role_type = sa.Enum(Role, name="role", create_type=False)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    kind: Mapped[WorkspaceKind] = mapped_column(
        workspace_kind_type, nullable=False, server_default="standard"
    )
    demo_session_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        # Sweeper scans expired demo workspaces via this index
        sa.Index("ix_workspaces_kind_expires_at", "kind", "expires_at"),
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    github_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")


class Membership(Base):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[Role] = mapped_column(
        role_type, nullable=False, server_default="owner"
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
