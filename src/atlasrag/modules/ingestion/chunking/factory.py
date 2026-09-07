from atlasrag.contracts.chunking import Chunker, TextTokenizer
from atlasrag.contracts.types.chunking import ChunkingStrategy

from .fixed_token import DEFAULT_MAX_TOKENS, DEFAULT_OVERLAP_TOKENS, FixedTokenChunker
from .heading_aware import HeadingAwareChunker
from .tokenizer import ReferenceTextTokenizer

DEFAULT_STRATEGY = ChunkingStrategy.HEADING_AWARE_V1


def create_chunker(
    *,
    strategy: ChunkingStrategy = DEFAULT_STRATEGY,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    tokenizer: TextTokenizer | None = None,
) -> Chunker:
    reference_tokenizer = tokenizer or ReferenceTextTokenizer()
    if strategy is ChunkingStrategy.FIXED_TOKEN_V1:
        return FixedTokenChunker(
            tokenizer=reference_tokenizer,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
    return HeadingAwareChunker(
        tokenizer=reference_tokenizer,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )


__all__ = ["DEFAULT_STRATEGY", "create_chunker"]
