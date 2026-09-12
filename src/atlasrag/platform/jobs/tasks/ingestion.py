import uuid
from datetime import UTC, datetime, timedelta

import structlog
from celery import Task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.bootstrap.core.config import get_settings
from atlasrag.contracts.object_storage import ObjectStorage
from atlasrag.modules.ingestion.chunking import ChunkerResolver, WhitespaceReferenceTokenizer
from atlasrag.modules.ingestion.extraction import create_extraction_pipeline
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline
from atlasrag.modules.ingestion.repositories.unit_of_work import (
    make_ingestion_unit_of_work_factory,
)
from atlasrag.modules.ingestion.services.artifact_loader import ArtifactLoader
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.workers.default_processor import DefaultIngestionProcessor
from atlasrag.modules.ingestion.workers.heartbeat import LeaseHeartbeat
from atlasrag.modules.ingestion.workers.job_handler import IngestionJobHandler
from atlasrag.modules.knowledge.repositories.document_artifact import (
    DocumentArtifactRepository,
)
from atlasrag.platform.jobs.celery_app import celery_app
from atlasrag.platform.jobs.constants import PROCESS_INGESTION_TASK
from atlasrag.platform.jobs.worker_runtime import get_worker_async_runtime
from atlasrag.platform.storage import MinioObjectStorage

logger = structlog.get_logger(__name__)


@celery_app.task(
    name=PROCESS_INGESTION_TASK,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_ingestion_item(self: Task, ingestion_item_id: str) -> None:
    item_id = uuid.UUID(ingestion_item_id)
    configuration = self.app.conf
    runtime = get_worker_async_runtime()
    runtime.initialize(
        database_url=configuration.atlas_database_url,
        database_echo=configuration.atlas_database_echo,
    )

    settings = get_settings()
    session_factory = runtime.session_factory
    lifecycle = IngestionLifecycleService(
        make_ingestion_unit_of_work_factory(session_factory),
        lease_duration=timedelta(seconds=configuration.atlas_ingestion_lease_seconds),
        max_attempts=configuration.atlas_ingestion_max_attempts,
        clock=lambda: datetime.now(UTC),
    )
    object_storage = MinioObjectStorage(
        endpoint_url=settings.MINIO_ENDPOINT_URL,
        use_ssl=settings.MINIO_USE_SSL,
        access_key=settings.MINIO_ROOT_USER,
        secret_key=settings.MINIO_ROOT_PASSWORD,
        bucket=settings.MINIO_BUCKET,
        region=settings.MINIO_REGION,
    )
    runtime.run(
        _handle_item(
            item_id=item_id,
            lifecycle=lifecycle,
            session_factory=session_factory,
            object_storage=object_storage,
            extraction_pipeline=create_extraction_pipeline(settings),
            heartbeat_seconds=configuration.atlas_ingestion_heartbeat_seconds,
        )
    )
    logger.info("ingestion_item_processed", ingestion_item_id=ingestion_item_id)


async def _handle_item(
    *,
    item_id: uuid.UUID,
    lifecycle: IngestionLifecycleService,
    session_factory: async_sessionmaker[AsyncSession],
    object_storage: ObjectStorage,
    extraction_pipeline: ExtractionPipeline,
    heartbeat_seconds: int,
) -> None:
    session = session_factory()
    try:
        handler = IngestionJobHandler(
            lifecycle=lifecycle,
            processor=DefaultIngestionProcessor(
                artifact_loader=ArtifactLoader(
                    artifact_repository=DocumentArtifactRepository(session),
                    object_storage=object_storage,
                ),
                extraction_pipeline=extraction_pipeline,
                lifecycle=lifecycle,
                chunker_resolver=ChunkerResolver(
                    tokenizers={
                        (WhitespaceReferenceTokenizer.name, WhitespaceReferenceTokenizer.version): (
                            WhitespaceReferenceTokenizer()
                        )
                    }
                ),
            ),
            heartbeat=LeaseHeartbeat(
                lifecycle,
                interval=timedelta(seconds=heartbeat_seconds),
            ),
        )
        await handler.handle(ingestion_item_id=item_id)
    finally:
        await session.close()


__all__ = ["process_ingestion_item"]
