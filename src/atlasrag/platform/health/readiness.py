from atlasrag.contracts.health import ReadinessProbe, ReadinessReport


class ReadinessService:
    def __init__(self, database_probe: ReadinessProbe) -> None:
        self._database_probe = database_probe

    async def check(self) -> ReadinessReport:
        return ReadinessReport(database_ready=await self._database_probe.check())


__all__ = ["ReadinessService"]
