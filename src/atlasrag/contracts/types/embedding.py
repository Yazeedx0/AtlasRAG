import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from atlasrag.contracts.types.ai_types import AiProvider, EmbeddingInputType

_EMPTY_CONFIGURATION: Mapping[str, object] = MappingProxyType({})


class EmbeddingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VectorDistanceMetric(StrEnum):
    COSINE = "cosine"
    INNER_PRODUCT = "inner_product"
    EUCLIDEAN = "euclidean"


@dataclass(frozen=True, slots=True)
class EmbeddingModelIdentity:
    provider: AiProvider
    model_name: str
    model_revision: str
    dimension: int
    distance_metric: VectorDistanceMetric
    max_input_tokens: int | None = None
    configuration: Mapping[str, object] = _EMPTY_CONFIGURATION

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise ValueError("dimension must be positive")
        if not self.model_name.strip():
            raise ValueError("model_name must be a non-empty string")
        if not self.model_revision.strip():
            raise ValueError("model_revision must be a non-empty string")
        if self.max_input_tokens is not None and self.max_input_tokens <= 0:
            raise ValueError("max_input_tokens must be positive when provided")


@dataclass(frozen=True, slots=True)
class EmbeddingModelState:
    id: uuid.UUID
    provider: AiProvider
    model_name: str
    model_revision: str
    dimension: int
    distance_metric: VectorDistanceMetric
    max_input_tokens: int | None
    configuration: dict[str, object]
    configuration_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EmbeddingRunState:
    id: uuid.UUID
    ingestion_item_id: uuid.UUID
    embedding_model_id: uuid.UUID
    configuration: dict[str, object]
    configuration_hash: str
    status: EmbeddingStatus
    attempt_count: int
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    error_code: str | None
    error_message: str | None
    execution_metadata: dict[str, object]
    created_by_principal_id: uuid.UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimedEmbeddingRun:
    embedding_run_id: uuid.UUID
    ingestion_item_id: uuid.UUID
    embedding_model_id: uuid.UUID
    attempt_number: int
    claimed_at: datetime
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class EmbeddableChunk:
    chunk_id: uuid.UUID
    chunk_index: int
    content: str
    token_count: int


@dataclass(frozen=True, slots=True)
class EmbeddingInput:
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    index: int
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    input_tokens: int | None = None
    total_tokens: int | None = None

    def merged_with(self, other: "EmbeddingUsage") -> "EmbeddingUsage":
        return EmbeddingUsage(
            input_tokens=_added(self.input_tokens, other.input_tokens),
            total_tokens=_added(self.total_tokens, other.total_tokens),
        )


@dataclass(frozen=True, slots=True)
class EmbeddingBatchRequest:
    model_name: str
    inputs: tuple[EmbeddingInput, ...]
    input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    vectors: tuple[EmbeddingVector, ...]
    model: str
    usage: EmbeddingUsage = field(default_factory=EmbeddingUsage)


@dataclass(frozen=True, slots=True)
class ChunkVector:
    chunk_id: uuid.UUID
    values: tuple[float, ...]


def _added(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


__all__ = [
    "ChunkVector",
    "ClaimedEmbeddingRun",
    "EmbeddableChunk",
    "EmbeddingBatchRequest",
    "EmbeddingBatchResult",
    "EmbeddingInput",
    "EmbeddingModelIdentity",
    "EmbeddingModelState",
    "EmbeddingRunState",
    "EmbeddingStatus",
    "EmbeddingUsage",
    "EmbeddingVector",
    "VectorDistanceMetric",
]
