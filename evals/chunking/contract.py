from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from atlasrag.contracts.types.extraction import ExtractedBlockType, ExtractedDocument

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})

CHUNK_METADATA_SPLIT_OF_BLOCK = "split_of_block"
CHUNK_METADATA_SECTION_INDEX = "section_index"


@dataclass(frozen=True, slots=True)
class ChunkingStrategy:
    name: str
    version: str
    configuration: Mapping[str, object] = field(default=_EMPTY_METADATA)


@dataclass(frozen=True, slots=True)
class EvalChunk:
    ordinal: int
    text: str
    heading_path: tuple[str, ...] = ()
    page_numbers: tuple[int, ...] = ()
    block_types: tuple[ExtractedBlockType, ...] = ()
    source_block_indexes: tuple[int, ...] = ()
    metadata: Mapping[str, object] = field(default=_EMPTY_METADATA)


@runtime_checkable
class EvalChunker(Protocol):
    @property
    def strategy(self) -> ChunkingStrategy:
        ...

    def chunk(self, *, document: ExtractedDocument) -> tuple[EvalChunk, ...]:
        ...


__all__ = [
    "CHUNK_METADATA_SECTION_INDEX",
    "CHUNK_METADATA_SPLIT_OF_BLOCK",
    "ChunkingStrategy",
    "EvalChunk",
    "EvalChunker",
]
