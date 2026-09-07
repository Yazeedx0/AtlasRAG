from dataclasses import dataclass
from typing import Protocol


class ReadinessProbe(Protocol):
    async def check(self) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    database_ready: bool
    broker_ready: bool
    workers_ready: bool

    @property
    def ready(self) -> bool:
        return self.database_ready and self.broker_ready and self.workers_ready


__all__ = ["ReadinessProbe", "ReadinessReport"]
