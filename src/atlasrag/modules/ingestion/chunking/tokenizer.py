import re

DEFAULT_CHARACTERS_PER_TOKEN = 4

_WORD_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class ReferenceTextTokenizer:
    def __init__(
        self,
        *,
        characters_per_token: int = DEFAULT_CHARACTERS_PER_TOKEN,
    ) -> None:
        if characters_per_token < 1:
            raise ValueError("characters_per_token must be positive")
        self._characters_per_token = characters_per_token

    def count_tokens(self, text: str) -> int:
        return len(self._token_cores(text))

    def split_tokens(self, text: str) -> tuple[str, ...]:
        cores = self._token_cores(text)
        if not cores:
            return ()

        segments: list[str] = []
        for index, (start, end) in enumerate(cores):
            leading = text[:start] if index == 0 else ""
            trailing_end = cores[index + 1][0] if index + 1 < len(cores) else len(text)
            trailing = text[end:trailing_end]
            segments.append(f"{leading}{text[start:end]}{trailing}")
        return tuple(segments)

    def _token_cores(self, text: str) -> list[tuple[int, int]]:
        cores: list[tuple[int, int]] = []
        for match in _WORD_PATTERN.finditer(text):
            start, end = match.span()
            if end - start <= self._characters_per_token:
                cores.append((start, end))
                continue
            for offset in range(start, end, self._characters_per_token):
                cores.append((offset, min(offset + self._characters_per_token, end)))
        return cores


__all__ = ["DEFAULT_CHARACTERS_PER_TOKEN", "ReferenceTextTokenizer"]
