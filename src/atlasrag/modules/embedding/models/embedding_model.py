import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from atlasrag.contracts.types.embedding import VectorDistanceMetric
from atlasrag.platform.database.base import Base

VECTOR_DISTANCE_METRIC_DB_ENUM = SqlEnum(
    VectorDistanceMetric,
    name="vector_distance_metric",
    schema="knowledge",
    values_callable=lambda enum: [member.value for member in enum],
)

MAX_VECTOR_DIMENSION = 16000


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"

    __table_args__ = (
        CheckConstraint(
            f"dimension > 0 AND dimension <= {MAX_VECTOR_DIMENSION}",
            name="valid_dimension",
        ),
        CheckConstraint(
            "max_input_tokens IS NULL OR max_input_tokens > 0",
            name="max_input_tokens_positive",
        ),
        CheckConstraint("length(btrim(model_name)) > 0", name="model_name_non_empty"),
        CheckConstraint("length(btrim(model_revision)) > 0", name="model_revision_non_empty"),
        UniqueConstraint(
            "provider",
            "model_name",
            "model_revision",
            "configuration_hash",
            name="uq_embedding_models_identity",
        ),
        {"schema": "knowledge"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(100), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_metric: Mapped[VectorDistanceMetric] = mapped_column(
        VECTOR_DISTANCE_METRIC_DB_ENUM,
        nullable=False,
    )
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    configuration: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = ["MAX_VECTOR_DIMENSION", "VECTOR_DISTANCE_METRIC_DB_ENUM", "EmbeddingModel"]
