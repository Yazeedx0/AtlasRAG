import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version as distribution_version
from typing import Protocol, runtime_checkable

from evals.core.errors import UnknownTokenizerError

UNICODE_WORD_TOKENIZER = "unicode-word-v1"
CL100K_TOKENIZER = "cl100k_base"
DEFAULT_TOKENIZER = UNICODE_WORD_TOKENIZER

_WORD_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class TokenizerIdentity:
    name: str
    version: str
    encoding: str | None = None


@runtime_checkable
class Tokenizer(Protocol):
    @property
    def identity(self) -> TokenizerIdentity:
        ...

    def tokenize(self, text: str) -> tuple[str, ...]:
        ...

    def detokenize(self, tokens: Sequence[str]) -> str:
        ...

    def count(self, text: str) -> int:
        ...


class UnicodeWordTokenizer:
    __slots__ = ()

    @property
    def identity(self) -> TokenizerIdentity:
        return TokenizerIdentity(name="unicode-word", version="1", encoding=None)

    def tokenize(self, text: str) -> tuple[str, ...]:
        return tuple(_WORD_PATTERN.findall(text))

    def detokenize(self, tokens: Sequence[str]) -> str:
        return " ".join(tokens)

    def count(self, text: str) -> int:
        return len(self.tokenize(text))


class TiktokenTokenizer:
    __slots__ = ("_encoding", "_identity")

    def __init__(self, *, encoding_name: str = CL100K_TOKENIZER) -> None:
        import tiktoken

        self._encoding = tiktoken.get_encoding(encoding_name)
        self._identity = TokenizerIdentity(
            name="tiktoken",
            version=distribution_version("tiktoken"),
            encoding=encoding_name,
        )

    @property
    def identity(self) -> TokenizerIdentity:
        return self._identity

    def tokenize(self, text: str) -> tuple[str, ...]:
        pieces: list[str] = []
        for token_id in self._encoding.encode(text):
            pieces.append(self._encoding.decode([token_id]))
        return tuple(pieces)

    def detokenize(self, tokens: Sequence[str]) -> str:
        return "".join(tokens)

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))


def create_tokenizer(name: str) -> Tokenizer:
    if name == UNICODE_WORD_TOKENIZER:
        return UnicodeWordTokenizer()
    if name == CL100K_TOKENIZER:
        return TiktokenTokenizer(encoding_name=CL100K_TOKENIZER)
    raise UnknownTokenizerError(name)


__all__ = [
    "CL100K_TOKENIZER",
    "DEFAULT_TOKENIZER",
    "UNICODE_WORD_TOKENIZER",
    "TiktokenTokenizer",
    "Tokenizer",
    "TokenizerIdentity",
    "UnicodeWordTokenizer",
    "create_tokenizer",
]
