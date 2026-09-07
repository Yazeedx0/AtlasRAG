from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType

import pytest
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)

from evals.chunking.contract import ChunkingStrategy, EvalChunk
from evals.core.tokenization import Tokenizer, UnicodeWordTokenizer


class StubChunker:
    def __init__(
        self,
        *,
        chunks_by_document: Mapping[str, Sequence[EvalChunk]],
        strategy: ChunkingStrategy,
    ) -> None:
        self._chunks_by_document = chunks_by_document
        self._strategy = strategy

    @property
    def strategy(self) -> ChunkingStrategy:
        return self._strategy

    def chunk(self, *, document: ExtractedDocument) -> tuple[EvalChunk, ...]:
        return tuple(self._chunks_by_document[document.blocks[0].text])


class DriftingChunker:
    def __init__(self) -> None:
        self._calls = 0

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy(name="drifting", version="1")

    def chunk(self, *, document: ExtractedDocument) -> tuple[EvalChunk, ...]:
        self._calls += 1
        return (EvalChunk(ordinal=0, text=f"call {self._calls}"),)


@pytest.fixture
def tokenizer() -> Tokenizer:
    return UnicodeWordTokenizer()


@pytest.fixture
def build_block() -> Callable[..., ExtractedBlock]:
    def factory(
        text: str,
        *,
        block_type: ExtractedBlockType = ExtractedBlockType.PARAGRAPH,
        page_number: int | None = 1,
        metadata: Mapping[str, object] | None = None,
    ) -> ExtractedBlock:
        return ExtractedBlock(
            text=text,
            block_type=block_type,
            page_number=page_number,
            metadata=MappingProxyType(dict(metadata or {})),
        )

    return factory


@pytest.fixture
def build_document() -> Callable[..., ExtractedDocument]:
    def factory(*blocks: ExtractedBlock) -> ExtractedDocument:
        return ExtractedDocument(blocks=blocks)

    return factory


@pytest.fixture
def build_chunk() -> Callable[..., EvalChunk]:
    def factory(
        text: str,
        *,
        ordinal: int = 0,
        heading_path: tuple[str, ...] = (),
        page_numbers: tuple[int, ...] = (),
        block_types: tuple[ExtractedBlockType, ...] = (),
    ) -> EvalChunk:
        return EvalChunk(
            ordinal=ordinal,
            text=text,
            heading_path=heading_path,
            page_numbers=page_numbers,
            block_types=block_types,
        )

    return factory


@pytest.fixture
def build_stub_chunker() -> Callable[..., StubChunker]:
    def factory(
        chunks_by_document: Mapping[str, Sequence[EvalChunk]],
        *,
        name: str = "stub",
        version: str = "1",
    ) -> StubChunker:
        return StubChunker(
            chunks_by_document=chunks_by_document,
            strategy=ChunkingStrategy(name=name, version=version),
        )

    return factory


@pytest.fixture
def drifting_chunker() -> DriftingChunker:
    return DriftingChunker()
