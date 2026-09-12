import re

_TOKEN_RE = re.compile(r"\S+")


class WhitespaceReferenceTokenizer:
    """Stable local reference tokenizer with explicit whitespace-token semantics."""

    name = "whitespace"
    version = "v1"

    def count(self, *, text: str) -> int:
        return len(_TOKEN_RE.findall(text))

    def split(
        self,
        *,
        text: str,
        max_tokens: int,
        overlap_tokens: int,
    ) -> tuple[str, ...]:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if overlap_tokens < 0 or overlap_tokens >= max_tokens:
            raise ValueError("overlap_tokens must be non-negative and less than max_tokens")

        tokens = _TOKEN_RE.findall(text)
        if not tokens:
            return ()

        step = max_tokens - overlap_tokens
        pieces: list[str] = []
        index = 0
        while index < len(tokens):
            end = min(index + max_tokens, len(tokens))
            pieces.append(" ".join(tokens[index:end]))
            if end == len(tokens):
                break
            index += step
        return tuple(pieces)


__all__ = ["WhitespaceReferenceTokenizer"]
