from collections.abc import Mapping
from dataclasses import dataclass

CONFIGURATION_KEY = "embedding"


@dataclass(frozen=True, slots=True)
class EmbeddingRunConfig:
    batch_size: int
    max_batch_tokens: int
    concurrency: int
    max_provider_attempts: int
    retry_initial_backoff_seconds: float
    retry_max_backoff_seconds: float
    max_chars_per_token: int

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.max_batch_tokens <= 0:
            raise ValueError("max_batch_tokens must be positive")
        if self.concurrency <= 0:
            raise ValueError("concurrency must be positive")
        if self.max_provider_attempts <= 0:
            raise ValueError("max_provider_attempts must be positive")
        if self.retry_initial_backoff_seconds <= 0:
            raise ValueError("retry_initial_backoff_seconds must be positive")
        if self.retry_max_backoff_seconds < self.retry_initial_backoff_seconds:
            raise ValueError(
                "retry_max_backoff_seconds must not be smaller than "
                "retry_initial_backoff_seconds"
            )
        if self.max_chars_per_token <= 0:
            raise ValueError("max_chars_per_token must be positive")

    @classmethod
    def from_run_configuration(cls, configuration: Mapping[str, object]) -> "EmbeddingRunConfig":
        raw = configuration.get(CONFIGURATION_KEY)
        if not isinstance(raw, Mapping):
            raise ValueError("embedding run configuration must contain an embedding object")
        return cls(
            batch_size=_required_int(raw, "batch_size"),
            max_batch_tokens=_required_int(raw, "max_batch_tokens"),
            concurrency=_required_int(raw, "concurrency"),
            max_provider_attempts=_required_int(raw, "max_provider_attempts"),
            retry_initial_backoff_seconds=_required_float(raw, "retry_initial_backoff_seconds"),
            retry_max_backoff_seconds=_required_float(raw, "retry_max_backoff_seconds"),
            max_chars_per_token=_required_int(raw, "max_chars_per_token"),
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "batch_size": self.batch_size,
            "max_batch_tokens": self.max_batch_tokens,
            "concurrency": self.concurrency,
            "max_provider_attempts": self.max_provider_attempts,
            "retry_initial_backoff_seconds": self.retry_initial_backoff_seconds,
            "retry_max_backoff_seconds": self.retry_max_backoff_seconds,
            "max_chars_per_token": self.max_chars_per_token,
        }


DEFAULT_EMBEDDING_RUN_CONFIG = EmbeddingRunConfig(
    batch_size=128,
    max_batch_tokens=100_000,
    concurrency=4,
    max_provider_attempts=4,
    retry_initial_backoff_seconds=0.5,
    retry_max_backoff_seconds=30.0,
    max_chars_per_token=4,
)


def _required_int(values: Mapping[str, object], name: str) -> int:
    value = values.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _required_float(values: Mapping[str, object], name: str) -> float:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    return float(value)


__all__ = [
    "CONFIGURATION_KEY",
    "DEFAULT_EMBEDDING_RUN_CONFIG",
    "EmbeddingRunConfig",
]
