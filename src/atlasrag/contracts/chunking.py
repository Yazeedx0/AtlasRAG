from typing import Protocol, runtime_checkable

from atlasrag.contracts.types.chunking import ChunkDraft
from atlasrag.contracts.types.extraction import ExtractedDocument


@runtime_checkable
class ReferenceTokenizer(Protocol):
    def count(self, *, text: str) -> int:
        ...

    def split(
        self,
        *,
        text: str,
        max_tokens: int,
        overlap_tokens: int,
    ) -> tuple[str, ...]:
        ...


@runtime_checkable
class Chunker(Protocol):
    def chunk(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None = None,
    ) -> tuple[ChunkDraft, ...]:
        ...


__all__ = ["Chunker", "ReferenceTokenizer"]
