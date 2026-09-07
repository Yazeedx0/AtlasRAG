import asyncio

from atlasrag.contracts.health import ReadinessProbe, ReadinessReport


class ReadinessService:
    def __init__(
        self,
        database_probe: ReadinessProbe,
        broker_probe: ReadinessProbe,
        worker_probe: ReadinessProbe,
    ) -> None:
        self._database_probe = database_probe
        self._broker_probe = broker_probe
        self._worker_probe = worker_probe

    async def check(self) -> ReadinessReport:
        database_ready, broker_ready, workers_ready = await asyncio.gather(
            self._database_probe.check(),
            self._broker_probe.check(),
            self._worker_probe.check(),
        )
        return ReadinessReport(
            database_ready=database_ready,
            broker_ready=broker_ready,
            workers_ready=workers_ready,
        )


__all__ = ["ReadinessService"]
