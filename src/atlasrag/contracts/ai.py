from typing import Protocol, runtime_checkable

from atlasrag.contracts.types.ai_types import (
    EmbeddingInputType,
    GeneratedText,
    RankedDocument,
)


@runtime_checkable
class TextGenerator(Protocol):
    async def generate(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int,
    ) -> GeneratedText:
        ...


@runtime_checkable
class Embedder(Protocol):
    async def embed(
        self,
        *,
        texts: list[str],
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> list[list[float]]:
        ...


@runtime_checkable
class Reranker(Protocol):
    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[RankedDocument]:
        ...


__all__ = ["Embedder", "Reranker", "TextGenerator"]
