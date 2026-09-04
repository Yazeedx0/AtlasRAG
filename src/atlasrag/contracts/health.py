from dataclasses import dataclass
from typing import Protocol


class ReadinessProbe(Protocol):
    async def check(self) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    database_ready: bool

    @property
    def ready(self) -> bool:
        return self.database_ready


__all__ = ["ReadinessProbe", "ReadinessReport"]
