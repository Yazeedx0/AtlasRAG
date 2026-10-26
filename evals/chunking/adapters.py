from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from atlasrag.contracts.types.extraction import ExtractedBlockType, ExtractedDocument

from evals.chunking.contract import ChunkingStrategy, EvalChunk


def _no_heading_path(chunk: object) -> tuple[str, ...]:
    return ()


def _no_pages(chunk: object) -> tuple[int, ...]:
    return ()


def _no_block_types(chunk: object) -> tuple[ExtractedBlockType, ...]:
    return ()


def _no_block_indexes(chunk: object) -> tuple[int, ...]:
    return ()


def _no_metadata(chunk: object) -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ChunkProjection[T]:
    text: Callable[[T], str]
    heading_path: Callable[[T], tuple[str, ...]] = _no_heading_path
    page_numbers: Callable[[T], tuple[int, ...]] = _no_pages
    block_types: Callable[[T], tuple[ExtractedBlockType, ...]] = _no_block_types
    source_block_indexes: Callable[[T], tuple[int, ...]] = _no_block_indexes
    metadata: Callable[[T], Mapping[str, object]] = _no_metadata


class AdaptedChunker[T]:
    __slots__ = ("_produce", "_projection", "_strategy")

    def __init__(
        self,
        *,
        strategy: ChunkingStrategy,
        produce: Callable[[ExtractedDocument], Sequence[T]],
        projection: ChunkProjection[T],
    ) -> None:
        self._strategy = strategy
        self._produce = produce
        self._projection = projection

    @property
    def strategy(self) -> ChunkingStrategy:
        return self._strategy

    def chunk(self, *, document: ExtractedDocument) -> tuple[EvalChunk, ...]:
        projection = self._projection
        return tuple(
            EvalChunk(
                ordinal=ordinal,
                text=projection.text(produced),
                heading_path=projection.heading_path(produced),
                page_numbers=projection.page_numbers(produced),
                block_types=projection.block_types(produced),
                source_block_indexes=projection.source_block_indexes(produced),
                metadata=MappingProxyType(dict(projection.metadata(produced))),
            )
            for ordinal, produced in enumerate(self._produce(document))
        )


__all__ = ["AdaptedChunker", "ChunkProjection"]
