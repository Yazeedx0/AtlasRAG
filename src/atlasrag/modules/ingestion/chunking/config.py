from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ChunkingStrategy(StrEnum):
    FIXED_TOKEN_V1 = "fixed_token_v1"  # noqa: S105
    HEADING_AWARE_V1 = "heading_aware_v1"


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    strategy: ChunkingStrategy
    reference_tokenizer: str
    reference_tokenizer_version: str
    max_tokens: int
    overlap_tokens: int
    preserve_tables: bool

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be non-negative and less than max_tokens")
        if not self.reference_tokenizer.strip() or not self.reference_tokenizer_version.strip():
            raise ValueError("reference tokenizer identity and version are required")

    @classmethod
    def from_run_configuration(cls, configuration: Mapping[str, object]) -> "ChunkingConfig":
        raw_chunking = configuration.get("chunking")
        if not isinstance(raw_chunking, Mapping):
            raise ValueError("ingestion run configuration must contain a chunking object")
        strategy = ChunkingStrategy(_required_string(raw_chunking, "strategy"))
        max_tokens = _required_int(raw_chunking, "max_tokens")
        overlap_tokens = _required_int(raw_chunking, "overlap_tokens")
        preserve_tables = raw_chunking.get("preserve_tables")
        if not isinstance(preserve_tables, bool):
            raise ValueError("preserve_tables must be a boolean")
        return cls(
            strategy=strategy,
            reference_tokenizer=_required_string(raw_chunking, "reference_tokenizer"),
            reference_tokenizer_version=_required_string(
                raw_chunking,
                "reference_tokenizer_version",
            ),
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            preserve_tables=preserve_tables,
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "strategy": self.strategy.value,
            "reference_tokenizer": self.reference_tokenizer,
            "reference_tokenizer_version": self.reference_tokenizer_version,
            "max_tokens": self.max_tokens,
            "overlap_tokens": self.overlap_tokens,
            "preserve_tables": self.preserve_tables,
        }


DEFAULT_CHUNKING_CONFIG = ChunkingConfig(
    strategy=ChunkingStrategy.HEADING_AWARE_V1,
    reference_tokenizer="whitespace",
    reference_tokenizer_version="v1",
    max_tokens=512,
    overlap_tokens=64,
    preserve_tables=True,
)


def _required_string(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_int(values: Mapping[str, object], name: str) -> int:
    value = values.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


__all__ = ["DEFAULT_CHUNKING_CONFIG", "ChunkingConfig", "ChunkingStrategy"]
