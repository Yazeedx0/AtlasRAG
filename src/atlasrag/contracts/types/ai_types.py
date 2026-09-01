from dataclasses import dataclass
from enum import StrEnum


class AiProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    COHERE = "cohere"
    GEMINI = "gemini"


class AiCapability(StrEnum):
    GENERATION = "generation"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class EmbeddingInputType(StrEnum):
    DOCUMENT = "document"
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class GeneratedText:
    text: str
    model: str


@dataclass(frozen=True, slots=True)
class RankedDocument:
    index: int
    relevance_score: float
