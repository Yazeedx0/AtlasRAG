import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from celery.contrib.testing.worker import start_worker
from testcontainers.redis import RedisContainer

from atlasrag.contracts.types.embedding import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingStatus,
    EmbeddingUsage,
    EmbeddingVector,
)
from atlasrag.contracts.types.jobs import JobType
from atlasrag.platform.jobs import tasks as _tasks  # noqa: F401
from atlasrag.platform.jobs.celery_app import create_celery_app
from atlasrag.platform.jobs.celery_dispatcher import CeleryTaskDispatcher
from atlasrag.platform.jobs.publisher import OutboxPublisher
from atlasrag.platform.jobs.tasks import embedding as embedding_task
from atlasrag.platform.jobs.unit_of_work import make_job_outbox_unit_of_work_factory
from atlasrag.platform.jobs.worker_runtime import get_worker_async_runtime

from .conftest import (
    DIMENSION,
    default_model_identity,
    embedding_run_configuration,
    stored_embeddings,
)

pytestmark = pytest.mark.integration

CHUNK_COUNT = 75
BATCH_SIZE = 16
COMPLETION_TIMEOUT_SECONDS = 60


class RecordedProvider:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        self.batch_sizes.append(len(request.inputs))
        return EmbeddingBatchResult(
            vectors=tuple(
                EmbeddingVector(
                    index=item.index,
                    values=tuple(float(item.index) for _ in range(DIMENSION)),
                )
                for item in reversed(request.inputs)
            ),
            model=request.model_name,
            usage=EmbeddingUsage(
                input_tokens=len(request.inputs),
                total_tokens=len(request.inputs),
            ),
        )


@pytest.fixture
def redis_broker_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as redis:
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(redis.port)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
def worker_runtime() -> Iterator[None]:
    get_worker_async_runtime().shutdown()
    yield
    get_worker_async_runtime().shutdown()


async def wait_for_completion(world, run_id) -> None:
    deadline = datetime.now(UTC) + timedelta(seconds=COMPLETION_TIMEOUT_SECONDS)
    while datetime.now(UTC) < deadline:
        run = await world.embedding.find_run(run_id=run_id)
        if run is not None and run.status is not EmbeddingStatus.PENDING:
            if run.status in (EmbeddingStatus.COMPLETED, EmbeddingStatus.FAILED):
                return
        await asyncio.sleep(0.25)


@pytest.mark.asyncio
async def test_outbox_publishes_to_redis_and_the_worker_embeds_every_chunk(
    identity_database,
    realtime_embedding_world,
    seed_realtime_completed_item,
    redis_broker_url: str,
    worker_runtime: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session_factory = identity_database
    world = realtime_embedding_world
    seeded = await seed_realtime_completed_item(chunk_count=CHUNK_COUNT)
    model_id = await world.registry.register(identity=default_model_identity())
    run_id = await world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(batch_size=BATCH_SIZE, concurrency=2),
    )

    provider = RecordedProvider()
    monkeypatch.setattr(
        embedding_task,
        "create_embedding_provider",
        lambda settings, provider=None: provider,  # noqa: ARG005
    )

    celery_app = create_celery_app(
        broker_url=redis_broker_url,
        database_url=str(engine.url.render_as_string(hide_password=False)),
        database_echo=False,
        outbox_publish_batch_size=100,
        outbox_publish_lease_seconds=60,
        embedding_lease_seconds=120,
        embedding_heartbeat_seconds=30,
        embedding_max_attempts=3,
    )
    celery_app.loader.import_default_modules()

    publisher = OutboxPublisher(
        make_job_outbox_unit_of_work_factory(session_factory),
        CeleryTaskDispatcher(celery_app),
        lease_duration=timedelta(minutes=1),
        clock=lambda: datetime.now(UTC),
    )

    with start_worker(
        celery_app,
        pool="solo",
        queues=["atlasrag.embedding"],
        perform_ping_check=False,
    ):
        report = await publisher.publish_pending(limit=10)
        await wait_for_completion(world, run_id)

    run = await world.embedding.find_run(run_id=run_id)
    rows = await stored_embeddings(world, model_id)
    item = await world.ingestion.find_item(item_id=seeded.ingestion_item_id)

    assert report.published == 1
    assert run is not None
    assert run.status is EmbeddingStatus.COMPLETED
    assert run.attempt_count == 1
    assert run.error_code is None
    assert len(rows) == CHUNK_COUNT
    assert {row.chunk_id for row in rows} == set(seeded.chunk_ids)
    assert all(len(row.embedding) == DIMENSION for row in rows)
    assert all(row.embedding_run_id == run_id for row in rows)
    assert provider.batch_sizes == [16, 16, 16, 16, 11]
    assert run.execution_metadata["embedding"]["embedded_chunk_count"] == CHUNK_COUNT
    assert item is not None
    assert item.activated_at is None


@pytest.mark.asyncio
async def test_embedding_outbox_job_maps_to_the_embedding_queue_task(
    identity_database,
    realtime_embedding_world,
    seed_realtime_completed_item,
) -> None:
    _, session_factory = identity_database
    world = realtime_embedding_world
    seeded = await seed_realtime_completed_item(chunk_count=2)
    model_id = await world.registry.register(identity=default_model_identity())
    run_id = await world.embedding.create_run(
        ingestion_item_id=seeded.ingestion_item_id,
        embedding_model_id=model_id,
        configuration=embedding_run_configuration(),
    )

    class RecordingDispatcher:
        def __init__(self) -> None:
            self.published: list[tuple[str, dict[str, object]]] = []

        def publish(self, *, task_name: str, payload: dict[str, object]) -> None:
            self.published.append((task_name, payload))

    dispatcher = RecordingDispatcher()
    publisher = OutboxPublisher(
        make_job_outbox_unit_of_work_factory(session_factory),
        dispatcher,
        lease_duration=timedelta(minutes=1),
        clock=lambda: datetime.now(UTC),
    )

    report = await publisher.publish_pending(limit=10)

    assert report.published == 1
    assert dispatcher.published == [
        ("atlasrag.embedding.process", {"embedding_run_id": str(run_id)})
    ]
    assert JobType.PROCESS_EMBEDDING.value == "embedding.process"
