from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies.knowledge import (
    get_document_artifact_upload_service,
    get_document_management_service,
    get_document_version_management_service,
)
from apps.api.dependencies.storage import get_object_storage
from atlasrag.bootstrap.core.config import get_settings
from atlasrag.contracts.object_storage import ObjectStorage
from atlasrag.modules.ingestion.extraction import create_extraction_pipeline
from atlasrag.modules.ingestion.repositories.unit_of_work import (
    make_ingestion_unit_of_work_factory,
)
from atlasrag.modules.ingestion.services.artifact_extraction import (
    ArtifactExtractionService,
)
from atlasrag.modules.ingestion.services.artifact_loader import ArtifactLoader
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
)
from atlasrag.modules.ingestion.services.ingestion_pipeline import IngestionPipelineService
from atlasrag.modules.knowledge.repositories.document_artifact import (
    DocumentArtifactRepository,
)
from atlasrag.modules.knowledge.services.document_artifact_upload import (
    DocumentArtifactUploadService,
)
from atlasrag.modules.knowledge.services.document_management import (
    DocumentManagementService,
)
from atlasrag.modules.knowledge.services.document_version_management import (
    DocumentVersionManagementService,
)
from atlasrag.platform.database.session import async_session_factory


async def get_artifact_extraction_service(
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> AsyncGenerator[ArtifactExtractionService, None]:
    session: AsyncSession = async_session_factory()
    try:
        yield ArtifactExtractionService(
            artifact_loader=ArtifactLoader(
                artifact_repository=DocumentArtifactRepository(session),
                object_storage=object_storage,
            ),
            extraction_pipeline=create_extraction_pipeline(get_settings()),
        )
    finally:
        await session.close()


def get_ingestion_lifecycle_service() -> IngestionLifecycleService:
    settings = get_settings()
    return IngestionLifecycleService(
        make_ingestion_unit_of_work_factory(async_session_factory),
        lease_duration=timedelta(seconds=settings.INGESTION_LEASE_SECONDS),
        max_attempts=settings.INGESTION_MAX_ATTEMPTS,
        clock=lambda: datetime.now(UTC),
    )


async def get_ingestion_pipeline_service(
    lifecycle: Annotated[
        IngestionLifecycleService,
        Depends(get_ingestion_lifecycle_service),
    ],
    upload_service: Annotated[
        DocumentArtifactUploadService,
        Depends(get_document_artifact_upload_service),
    ],
    document_service: Annotated[
        DocumentManagementService,
        Depends(get_document_management_service),
    ],
    version_service: Annotated[
        DocumentVersionManagementService,
        Depends(get_document_version_management_service),
    ],
) -> IngestionPipelineService:
    return IngestionPipelineService(
        document_service=document_service,
        version_service=version_service,
        upload_service=upload_service,
        lifecycle=lifecycle,
    )


__all__ = [
    "get_artifact_extraction_service",
    "get_ingestion_lifecycle_service",
    "get_ingestion_pipeline_service",
]
