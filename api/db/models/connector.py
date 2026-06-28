"""
Connector model — represents an external secret store or cloud auth target.

Auth credentials are never stored here; vault_auth_handle is a pointer into
HashiCorp Vault (D10). `connection` holds only non-secret connectivity details.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.types import connector_status_enum, connector_type_enum, environment_enum
from shared.models.enums import ConnectorStatus, ConnectorType, Environment


class Connector(Base):
    __tablename__ = "connectors"

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
    type: Mapped[ConnectorType] = mapped_column(connector_type_enum, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    environment: Mapped[Environment] = mapped_column(
        environment_enum, nullable=False, server_default="unknown"
    )
    path_prefix: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Non-secret connectivity config (host, region, etc.)
    connection: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    # Pointer into Vault — no secret stored in this table (D10)
    vault_auth_handle: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # {read, write, rotate, revoke} capability probe result
    capabilities: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    status: Mapped[ConnectorStatus] = mapped_column(
        connector_status_enum, nullable=False, server_default="untested"
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
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
        sa.Index("ix_connectors_workspace_type", "workspace_id", "type"),
    )
