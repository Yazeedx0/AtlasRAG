import pytest

from atlasrag.platform.health import ReadinessService


class StubProbe:
    def __init__(self, result: bool) -> None:
        self._result = result
        self.calls = 0

    async def check(self) -> bool:
        self.calls += 1
        return self._result


@pytest.mark.asyncio
async def test_readiness_is_true_only_when_every_dependency_answers() -> None:
    service = ReadinessService(StubProbe(True), StubProbe(True), StubProbe(True))

    report = await service.check()

    assert report.ready is True
    assert report.database_ready is True
    assert report.broker_ready is True
    assert report.workers_ready is True


@pytest.mark.asyncio
async def test_missing_workers_make_the_service_not_ready() -> None:
    service = ReadinessService(StubProbe(True), StubProbe(True), StubProbe(False))

    report = await service.check()

    assert report.ready is False
    assert report.workers_ready is False
    assert report.database_ready is True


@pytest.mark.asyncio
async def test_unreachable_broker_makes_the_service_not_ready() -> None:
    service = ReadinessService(StubProbe(True), StubProbe(False), StubProbe(True))

    report = await service.check()

    assert report.ready is False
    assert report.broker_ready is False


@pytest.mark.asyncio
async def test_every_probe_runs_even_when_one_fails() -> None:
    database = StubProbe(False)
    broker = StubProbe(True)
    workers = StubProbe(True)
    service = ReadinessService(database, broker, workers)

    report = await service.check()

    assert report.ready is False
    assert (database.calls, broker.calls, workers.calls) == (1, 1, 1)
