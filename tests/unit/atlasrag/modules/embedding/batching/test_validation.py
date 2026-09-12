import math
import uuid
from datetime import UTC, datetime

import pytest

from atlasrag.contracts.error.embedding_errors import (
    EmbeddingInputInvalid,
    EmbeddingInputTooLarge,
    EmbeddingVectorInvalid,
    InvalidEmbeddingResponse,
)
from atlasrag.contracts.types.ai_types import AiProvider
from atlasrag.contracts.types.embedding import (
    EmbeddableChunk,
    EmbeddingBatchResult,
    EmbeddingInput,
    EmbeddingModelState,
    EmbeddingVector,
    VectorDistanceMetric,
)
from atlasrag.modules.embedding.batching import build_inputs, ordered_vectors
from atlasrag.modules.embedding.config import DEFAULT_EMBEDDING_RUN_CONFIG

pytestmark = pytest.mark.unit

CONFIG = DEFAULT_EMBEDDING_RUN_CONFIG


def make_model(*, dimension: int = 3, max_input_tokens: int | None = 10) -> EmbeddingModelState:
    return EmbeddingModelState(
        id=uuid.uuid4(),
        provider=AiProvider.OPENAI,
        model_name="text-embedding-3-small",
        model_revision="v1",
        dimension=dimension,
        distance_metric=VectorDistanceMetric.COSINE,
        max_input_tokens=max_input_tokens,
        configuration={},
        configuration_hash="a" * 64,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def make_chunk(*, index: int = 0, content: str = "hello world") -> EmbeddableChunk:
    return EmbeddableChunk(
        chunk_id=uuid.uuid4(),
        chunk_index=index,
        content=content,
        token_count=2,
    )


def test_inputs_are_built_in_chunk_order() -> None:
    chunks = (make_chunk(index=0, content="a"), make_chunk(index=1, content="b"))

    inputs = build_inputs(chunks=chunks, model=make_model(), config=CONFIG)

    assert inputs == (EmbeddingInput(index=0, text="a"), EmbeddingInput(index=1, text="b"))


def test_blank_content_is_rejected() -> None:
    chunks = (make_chunk(content="   \n "),)

    with pytest.raises(EmbeddingInputInvalid):
        build_inputs(chunks=chunks, model=make_model(), config=CONFIG)


def test_input_that_cannot_fit_the_model_limit_is_rejected_without_truncation() -> None:
    model = make_model(max_input_tokens=4)
    oversized = "x" * (4 * CONFIG.max_chars_per_token + 1)
    chunks = (make_chunk(index=7, content=oversized),)

    with pytest.raises(EmbeddingInputTooLarge) as error:
        build_inputs(chunks=chunks, model=model, config=CONFIG)

    assert error.value.chunk_index == 7


def test_input_within_the_model_limit_is_passed_through_untouched() -> None:
    model = make_model(max_input_tokens=4)
    text = "x" * (4 * CONFIG.max_chars_per_token)
    chunks = (make_chunk(content=text),)

    inputs = build_inputs(chunks=chunks, model=model, config=CONFIG)

    assert inputs[0].text == text


def test_model_without_a_declared_limit_skips_the_size_guard() -> None:
    model = make_model(max_input_tokens=None)
    chunks = (make_chunk(content="x" * 100_000),)

    inputs = build_inputs(chunks=chunks, model=model, config=CONFIG)

    assert len(inputs[0].text) == 100_000


def test_vectors_are_reordered_by_the_provider_index() -> None:
    inputs = (EmbeddingInput(index=0, text="a"), EmbeddingInput(index=1, text="b"))
    result = EmbeddingBatchResult(
        vectors=(
            EmbeddingVector(index=1, values=(4.0, 5.0, 6.0)),
            EmbeddingVector(index=0, values=(1.0, 2.0, 3.0)),
        ),
        model="text-embedding-3-small",
    )

    assert ordered_vectors(result=result, inputs=inputs, dimension=3) == (
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
    )


def test_vector_count_mismatch_is_rejected() -> None:
    inputs = (EmbeddingInput(index=0, text="a"), EmbeddingInput(index=1, text="b"))
    result = EmbeddingBatchResult(
        vectors=(EmbeddingVector(index=0, values=(1.0, 2.0, 3.0)),),
        model="m",
    )

    with pytest.raises(InvalidEmbeddingResponse):
        ordered_vectors(result=result, inputs=inputs, dimension=3)


def test_duplicate_vector_index_is_rejected() -> None:
    inputs = (EmbeddingInput(index=0, text="a"), EmbeddingInput(index=1, text="b"))
    result = EmbeddingBatchResult(
        vectors=(
            EmbeddingVector(index=0, values=(1.0, 2.0, 3.0)),
            EmbeddingVector(index=0, values=(1.0, 2.0, 3.0)),
        ),
        model="m",
    )

    with pytest.raises(InvalidEmbeddingResponse):
        ordered_vectors(result=result, inputs=inputs, dimension=3)


def test_unknown_vector_index_is_rejected() -> None:
    inputs = (EmbeddingInput(index=0, text="a"),)
    result = EmbeddingBatchResult(
        vectors=(EmbeddingVector(index=9, values=(1.0, 2.0, 3.0)),),
        model="m",
    )

    with pytest.raises(InvalidEmbeddingResponse):
        ordered_vectors(result=result, inputs=inputs, dimension=3)


def test_wrong_dimension_is_rejected() -> None:
    inputs = (EmbeddingInput(index=0, text="a"),)
    result = EmbeddingBatchResult(
        vectors=(EmbeddingVector(index=0, values=(1.0, 2.0)),),
        model="m",
    )

    with pytest.raises(EmbeddingVectorInvalid):
        ordered_vectors(result=result, inputs=inputs, dimension=3)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_rejected(value: float) -> None:
    inputs = (EmbeddingInput(index=0, text="a"),)
    result = EmbeddingBatchResult(
        vectors=(EmbeddingVector(index=0, values=(1.0, value, 3.0)),),
        model="m",
    )

    with pytest.raises(EmbeddingVectorInvalid):
        ordered_vectors(result=result, inputs=inputs, dimension=3)


def test_non_numeric_values_are_rejected() -> None:
    inputs = (EmbeddingInput(index=0, text="a"),)
    result = EmbeddingBatchResult(
        vectors=(EmbeddingVector(index=0, values=("1.0", 2.0, 3.0)),),  # type: ignore[arg-type]
        model="m",
    )

    with pytest.raises(EmbeddingVectorInvalid):
        ordered_vectors(result=result, inputs=inputs, dimension=3)
