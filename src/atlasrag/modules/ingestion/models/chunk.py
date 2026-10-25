import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.platform.database.base import Base


class Chunk(Base):
    __tablename__ = "chunks"

    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint("length(btrim(content)) > 0", name="content_non_empty"),
        CheckConstraint(
            "content_type IN ('text', 'table', 'code', 'mixed')",
            name="valid_content_type",
        ),
        CheckConstraint("token_count >= 0", name="token_count_non_negative"),
        CheckConstraint(
            "page_start IS NULL OR page_start > 0",
            name="page_start_positive",
        ),
        CheckConstraint(
            "page_end IS NULL OR page_end > 0",
            name="page_end_positive",
        ),
        CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start",
            name="valid_page_range",
        ),
        UniqueConstraint("ingestion_item_id", "chunk_index", name="uq_chunks_item_index"),
        Index("ix_chunks_ingestion_item_id", "ingestion_item_id"),
        Index("ix_chunks_content_hash", "content_hash"),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.ingestion_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_path: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(35), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["Chunk"]
