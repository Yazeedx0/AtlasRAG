import uuid

import pytest

from atlasrag.contracts.types.embedding import EmbeddableChunk
from atlasrag.modules.embedding.batching import plan_batches
from atlasrag.modules.embedding.config import DEFAULT_EMBEDDING_RUN_CONFIG

pytestmark = pytest.mark.unit


def make_chunks(count: int, *, token_count: int = 10) -> tuple[EmbeddableChunk, ...]:
    return tuple(
        EmbeddableChunk(
            chunk_id=uuid.uuid4(),
            chunk_index=index,
            content=f"chunk {index}",
            token_count=token_count,
        )
        for index in range(count)
    )


def test_no_chunks_produce_no_batches() -> None:
    config = DEFAULT_EMBEDDING_RUN_CONFIG

    assert plan_batches(chunks=(), config=config) == ()


def test_batches_are_capped_by_item_count() -> None:
    config = DEFAULT_EMBEDDING_RUN_CONFIG.__class__(
        **{**DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(), "batch_size": 10}
    )
    chunks = make_chunks(25)

    batches = plan_batches(chunks=chunks, config=config)

    assert [len(batch.chunks) for batch in batches] == [10, 10, 5]
    assert [batch.ordinal for batch in batches] == [0, 1, 2]


def test_batches_are_capped_by_token_budget() -> None:
    config = DEFAULT_EMBEDDING_RUN_CONFIG.__class__(
        **{
            **DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(),
            "batch_size": 100,
            "max_batch_tokens": 25,
        }
    )
    chunks = make_chunks(6, token_count=10)

    batches = plan_batches(chunks=chunks, config=config)

    assert [len(batch.chunks) for batch in batches] == [2, 2, 2]


def test_chunk_order_is_preserved_across_batches() -> None:
    config = DEFAULT_EMBEDDING_RUN_CONFIG.__class__(
        **{**DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(), "batch_size": 3}
    )
    chunks = make_chunks(7)

    batches = plan_batches(chunks=chunks, config=config)
    flattened = [chunk.chunk_index for batch in batches for chunk in batch.chunks]

    assert flattened == list(range(7))


def test_single_oversized_chunk_still_forms_its_own_batch() -> None:
    config = DEFAULT_EMBEDDING_RUN_CONFIG.__class__(
        **{**DEFAULT_EMBEDDING_RUN_CONFIG.as_mapping(), "max_batch_tokens": 5}
    )
    chunks = make_chunks(2, token_count=50)

    batches = plan_batches(chunks=chunks, config=config)

    assert [len(batch.chunks) for batch in batches] == [1, 1]
