import math

from atlasrag.contracts.error.embedding_errors import (
    EmbeddingInputInvalid,
    EmbeddingInputTooLarge,
    EmbeddingVectorInvalid,
    InvalidEmbeddingResponse,
)
from atlasrag.contracts.types.embedding import (
    EmbeddableChunk,
    EmbeddingBatchResult,
    EmbeddingInput,
    EmbeddingModelState,
)
from atlasrag.modules.embedding.config import EmbeddingRunConfig

EMPTY_INPUT = "chunk content is empty"
INPUT_EXCEEDS_MODEL_LIMIT = "chunk content cannot fit the model input limit"
VECTOR_COUNT_MISMATCH = "vector count does not match the input count"
DUPLICATE_VECTOR_INDEX = "provider returned duplicate vector indexes"
UNKNOWN_VECTOR_INDEX = "provider returned an unknown vector index"
DIMENSION_MISMATCH = "vector dimension does not match the model dimension"
NON_FINITE_VECTOR_VALUE = "vector contains a non-finite value"


def build_inputs(
    *,
    chunks: tuple[EmbeddableChunk, ...],
    model: EmbeddingModelState,
    config: EmbeddingRunConfig,
) -> tuple[EmbeddingInput, ...]:
    inputs: list[EmbeddingInput] = []
    for index, chunk in enumerate(chunks):
        text = chunk.content
        if not text.strip():
            raise EmbeddingInputInvalid(chunk_index=chunk.chunk_index, reason=EMPTY_INPUT)
        _guard_input_size(chunk=chunk, model=model, config=config)
        inputs.append(EmbeddingInput(index=index, text=text))
    return tuple(inputs)


def ordered_vectors(
    *,
    result: EmbeddingBatchResult,
    inputs: tuple[EmbeddingInput, ...],
    dimension: int,
) -> tuple[tuple[float, ...], ...]:
    if len(result.vectors) != len(inputs):
        raise InvalidEmbeddingResponse(reason=VECTOR_COUNT_MISMATCH)

    expected_indexes = {item.index for item in inputs}
    by_index: dict[int, tuple[float, ...]] = {}
    for vector in result.vectors:
        if vector.index not in expected_indexes:
            raise InvalidEmbeddingResponse(reason=UNKNOWN_VECTOR_INDEX)
        if vector.index in by_index:
            raise InvalidEmbeddingResponse(reason=DUPLICATE_VECTOR_INDEX)
        by_index[vector.index] = _validated_values(values=vector.values, dimension=dimension)

    return tuple(by_index[item.index] for item in inputs)


def _validated_values(*, values: tuple[float, ...], dimension: int) -> tuple[float, ...]:
    if len(values) != dimension:
        raise EmbeddingVectorInvalid(reason=DIMENSION_MISMATCH)
    for value in values:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise EmbeddingVectorInvalid(reason=NON_FINITE_VECTOR_VALUE)
        if not math.isfinite(value):
            raise EmbeddingVectorInvalid(reason=NON_FINITE_VECTOR_VALUE)
    return values


def _guard_input_size(
    *,
    chunk: EmbeddableChunk,
    model: EmbeddingModelState,
    config: EmbeddingRunConfig,
) -> None:
    # ``token_count`` belongs to the chunking reference tokenizer, so it cannot decide
    # whether the provider will accept the text. The deterministic guard is a character
    # bound that no tokenizer can undercut; the provider stays authoritative and its
    # rejection is surfaced as ``EmbeddingInputTooLarge`` instead of truncating.
    if model.max_input_tokens is None:
        return None
    minimum_tokens = math.ceil(len(chunk.content) / config.max_chars_per_token)
    if minimum_tokens > model.max_input_tokens:
        raise EmbeddingInputTooLarge(
            chunk_index=chunk.chunk_index,
            reason=INPUT_EXCEEDS_MODEL_LIMIT,
        )
    return None


__all__ = [
    "DIMENSION_MISMATCH",
    "DUPLICATE_VECTOR_INDEX",
    "EMPTY_INPUT",
    "INPUT_EXCEEDS_MODEL_LIMIT",
    "NON_FINITE_VECTOR_VALUE",
    "UNKNOWN_VECTOR_INDEX",
    "VECTOR_COUNT_MISMATCH",
    "build_inputs",
    "ordered_vectors",
]
