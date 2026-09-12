import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.modules.embedding.models.embedding_model import MAX_VECTOR_DIMENSION
from atlasrag.platform.database.base import Base


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    __table_args__ = (
        PrimaryKeyConstraint("chunk_id", "embedding_model_id", name="pk_chunk_embeddings"),
        CheckConstraint(
            f"dimension > 0 AND dimension <= {MAX_VECTOR_DIMENSION}",
            name="valid_dimension",
        ),
        CheckConstraint(
            "vector_dims(embedding) = dimension",
            name="embedding_matches_dimension",
        ),
        Index("ix_chunk_embeddings_embedding_model_id", "embedding_model_id"),
        Index("ix_chunk_embeddings_embedding_run_id", "embedding_run_id"),
        {"schema": "knowledge"},
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.chunks.id", ondelete="CASCADE"),
        nullable=False,
    )

    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.embedding_models.id", ondelete="RESTRICT"),
        nullable=False,
    )

    embedding_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.embedding_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )

    dimension: Mapped[int] = mapped_column(Integer, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = ["ChunkEmbedding"]
