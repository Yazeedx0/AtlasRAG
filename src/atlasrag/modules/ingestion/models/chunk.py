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
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.contracts.types.chunking import ChunkContentType
from atlasrag.platform.database.base import Base

CHUNK_CONTENT_TYPE_DB_ENUM = SqlEnum(
    ChunkContentType,
    name="chunk_content_type",
    schema="knowledge",
    values_callable=lambda enum: [member.value for member in enum],
)


class Chunk(Base):
    __tablename__ = "chunks"

    __table_args__ = (
        CheckConstraint(
            "chunk_index >= 0",
            name="chunk_index_non_negative",
        ),
        CheckConstraint(
            "token_count > 0",
            name="token_count_positive",
        ),
        CheckConstraint(
            "length(btrim(content)) > 0",
            name="content_not_blank",
        ),
        CheckConstraint(
            """
            page_start IS NULL
            OR page_end IS NULL
            OR page_end >= page_start
            """,
            name="valid_page_range",
        ),
        CheckConstraint(
            "parent_chunk_id IS NULL OR parent_chunk_id <> id",
            name="parent_is_not_self",
        ),
        UniqueConstraint(
            "ingestion_item_id",
            "chunk_index",
            name="uq_chunks_item_chunk_index",
        ),
        Index(
            "ix_chunks_content_hash",
            "content_hash",
        ),
        Index(
            "ix_chunks_parent_chunk_id",
            "parent_chunk_id",
        ),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ingestion_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge.ingestion_items.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "knowledge.chunks.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_type: Mapped[ChunkContentType] = mapped_column(
        CHUNK_CONTENT_TYPE_DB_ENUM,
        nullable=False,
        server_default=text("'text'"),
    )

    section_title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    section_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )

    page_start: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    page_end: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    language_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
