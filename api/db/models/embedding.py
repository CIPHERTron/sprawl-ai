"""
Embedding model — pgvector similarity search over findings and investigation summaries.

Index: HNSW with cosine distance (fast approximate nearest-neighbour).
Dimension 768 matches nomic-embed-text (default local model via Ollama).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base

EMBEDDING_DIM = 768


class Embedding(Base):
    __tablename__ = "embeddings"

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
        sa.ForeignKey("secrets.id", ondelete="CASCADE"),
        nullable=True,
    )
    # 'finding_context' | 'investigation_summary'
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        # HNSW index defined in migration; referenced here for documentation
        # sa.Index("ix_embeddings_hnsw", "embedding", postgresql_using="hnsw",
        #          postgresql_ops={"embedding": "vector_cosine_ops"})
        # — Alembic can't render HNSW ops cleanly; managed via raw SQL in migration.
    )
