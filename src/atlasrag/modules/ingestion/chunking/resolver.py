from collections.abc import Callable, Mapping

from atlasrag.contracts.chunking import Chunker, ReferenceTokenizer

from .chunkers import FixedTokenChunker, HeadingAwareChunker
from .config import ChunkingConfig, ChunkingStrategy


class ChunkerResolver:
    def __init__(self, *, tokenizers: Mapping[tuple[str, str], ReferenceTokenizer]) -> None:
        self._tokenizers = dict(tokenizers)
        self._factories: Mapping[
            ChunkingStrategy,
            Callable[[ReferenceTokenizer, ChunkingConfig], Chunker],
        ] = {
            ChunkingStrategy.FIXED_TOKEN_V1: lambda tokenizer, config: FixedTokenChunker(
                tokenizer=tokenizer, config=config
            ),
            ChunkingStrategy.HEADING_AWARE_V1: lambda tokenizer, config: HeadingAwareChunker(
                tokenizer=tokenizer, config=config
            ),
        }

    def resolve(self, *, config: ChunkingConfig) -> Chunker:
        tokenizer = self._tokenizers.get(
            (config.reference_tokenizer, config.reference_tokenizer_version)
        )
        if tokenizer is None:
            raise ValueError("configured reference tokenizer is unavailable")
        return self._factories[config.strategy](tokenizer, config)


__all__ = ["ChunkerResolver"]
