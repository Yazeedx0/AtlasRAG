from dataclasses import dataclass

from atlasrag.contracts.types.embedding import EmbeddableChunk
from atlasrag.modules.embedding.config import EmbeddingRunConfig


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    ordinal: int
    chunks: tuple[EmbeddableChunk, ...]


def plan_batches(
    *,
    chunks: tuple[EmbeddableChunk, ...],
    config: EmbeddingRunConfig,
) -> tuple[EmbeddingBatch, ...]:
    batches: list[EmbeddingBatch] = []
    current: list[EmbeddableChunk] = []
    current_tokens = 0

    for chunk in chunks:
        exceeds_items = len(current) >= config.batch_size
        exceeds_tokens = bool(current) and (
            current_tokens + chunk.token_count > config.max_batch_tokens
        )
        if exceeds_items or exceeds_tokens:
            batches.append(EmbeddingBatch(ordinal=len(batches), chunks=tuple(current)))
            current = []
            current_tokens = 0
        current.append(chunk)
        current_tokens += chunk.token_count

    if current:
        batches.append(EmbeddingBatch(ordinal=len(batches), chunks=tuple(current)))
    return tuple(batches)


__all__ = ["EmbeddingBatch", "plan_batches"]
