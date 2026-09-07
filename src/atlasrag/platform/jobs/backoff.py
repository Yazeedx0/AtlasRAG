from dataclasses import dataclass
from datetime import timedelta

MAX_BACKOFF_EXPONENT = 32


@dataclass(frozen=True, slots=True)
class ExponentialBackoff:
    base: timedelta
    maximum: timedelta

    def __post_init__(self) -> None:
        if self.base.total_seconds() <= 0:
            raise ValueError("Backoff base must be positive")
        if self.maximum < self.base:
            raise ValueError("Backoff maximum must not be smaller than the base")

    def delay_for(self, *, attempt_number: int) -> timedelta:
        if attempt_number < 1:
            raise ValueError("Attempt number must be at least 1")
        exponent = min(attempt_number - 1, MAX_BACKOFF_EXPONENT)
        return min(self.base * (2**exponent), self.maximum)


__all__ = ["MAX_BACKOFF_EXPONENT", "ExponentialBackoff"]
