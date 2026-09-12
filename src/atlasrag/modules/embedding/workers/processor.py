from typing import Protocol

from atlasrag.contracts.types.embedding import ClaimedEmbeddingRun


class EmbeddingProcessor(Protocol):
    async def process(self, *, claim: ClaimedEmbeddingRun) -> None:
        ...


__all__ = ["EmbeddingProcessor"]
