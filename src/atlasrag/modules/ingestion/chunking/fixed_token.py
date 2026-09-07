from dataclasses import dataclass

from atlasrag.contracts.chunking import TextTokenizer
from atlasrag.contracts.types.chunking import (
    ChunkContentType,
    ChunkDraft,
    ChunkingStrategy,
)
from atlasrag.contracts.types.extraction import ExtractedDocument

from ._common import (
    ChunkPiece,
    content_type_for_block,
    finalize_pieces,
    page_range,
    token_windows,
    validate_token_bounds,
)
from .tokenizer import ReferenceTextTokenizer

DEFAULT_MAX_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64

_BLOCK_SEPARATOR = "\n\n"


@dataclass(frozen=True, slots=True)
class _FlatToken:
    text: str
    page_number: int | None
    content_type: ChunkContentType


class FixedTokenChunker:
    def __init__(
        self,
        *,
        tokenizer: TextTokenizer | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    ) -> None:
        validate_token_bounds(max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        self._tokenizer = tokenizer or ReferenceTextTokenizer()
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    def chunk(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None = None,
    ) -> tuple[ChunkDraft, ...]:
        tokens = self._flatten(document)
        pieces = [
            self._build_piece(tokens[start:end])
            for start, end in token_windows(
                len(tokens),
                max_tokens=self._max_tokens,
                overlap_tokens=self._overlap_tokens,
            )
        ]
        return finalize_pieces(
            pieces,
            tokenizer=self._tokenizer,
            language_code=language_code,
        )

    def _flatten(self, document: ExtractedDocument) -> list[_FlatToken]:
        tokens: list[_FlatToken] = []
        for block in document.blocks:
            text = block.text.strip()
            if not text:
                continue

            segments = self._tokenizer.split_tokens(text)
            if not segments:
                continue

            if tokens:
                previous = tokens[-1]
                tokens[-1] = _FlatToken(
                    text=f"{previous.text}{_BLOCK_SEPARATOR}",
                    page_number=previous.page_number,
                    content_type=previous.content_type,
                )

            content_type = content_type_for_block(block.block_type)
            tokens.extend(
                _FlatToken(
                    text=segment,
                    page_number=block.page_number,
                    content_type=content_type,
                )
                for segment in segments
            )
        return tokens

    def _build_piece(self, window: list[_FlatToken]) -> ChunkPiece:
        content_types = {token.content_type for token in window}
        content_type = (
            content_types.pop() if len(content_types) == 1 else ChunkContentType.TEXT
        )
        page_start, page_end = page_range([token.page_number for token in window])
        return ChunkPiece(
            content="".join(token.text for token in window),
            content_type=content_type,
            page_start=page_start,
            page_end=page_end,
            metadata={"strategy": ChunkingStrategy.FIXED_TOKEN_V1.value},
        )


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_OVERLAP_TOKENS",
    "FixedTokenChunker",
]
