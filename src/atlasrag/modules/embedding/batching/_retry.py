import random

from atlasrag.modules.embedding.config import EmbeddingRunConfig


def backoff_seconds(
    *,
    attempt_number: int,
    config: EmbeddingRunConfig,
    retry_after_seconds: float | None,
    jitter: float,
) -> float:
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return min(retry_after_seconds, config.retry_max_backoff_seconds)
    exponential = config.retry_initial_backoff_seconds * (2 ** (attempt_number - 1))
    return min(exponential, config.retry_max_backoff_seconds) * (0.5 + jitter / 2)


def default_jitter() -> float:
    return random.random()  # noqa: S311


__all__ = ["backoff_seconds", "default_jitter"]
