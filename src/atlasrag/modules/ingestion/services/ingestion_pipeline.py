import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

from atlasrag.contracts.documents import UploadDocumentArtifact
from atlasrag.contracts.types.ingestion import IngestionStatus
from atlasrag.modules.ingestion.chunking import DEFAULT_CHUNKING_CONFIG, ChunkingConfig
from atlasrag.modules.ingestion.services.ingestion_lifecycle import (
    IngestionLifecycleService,
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

DEFAULT_VERSION_LABEL = "v1"
DEFAULT_ARTIFACT_KEY = "source"


@dataclass(frozen=True, slots=True)
class IngestDocument:
    title: str
    source_name: str
    content_type: str
    content: bytes
    language_code: str
    canonical_key: str | None = None
    version_label: str = DEFAULT_VERSION_LABEL
    artifact_key: str = DEFAULT_ARTIFACT_KEY
    chunking_configuration: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class QueuedIngestion:
    document_id: UUID
    document_version_id: UUID
    artifact_id: UUID
    canonical_key: str
    ingestion_run_id: UUID
    ingestion_item_id: UUID
    status: IngestionStatus


class IngestionPipelineService:
    def __init__(
        self,
        *,
        document_service: DocumentManagementService,
        version_service: DocumentVersionManagementService,
        upload_service: DocumentArtifactUploadService,
        lifecycle: IngestionLifecycleService,
    ) -> None:
        self._document_service = document_service
        self._version_service = version_service
        self._upload_service = upload_service
        self._lifecycle = lifecycle

    async def ingest(
        self,
        command: IngestDocument,
        *,
        actor_principal_id: UUID,
    ) -> QueuedIngestion:
        canonical_key = command.canonical_key or f"ingestion-{uuid4()}"
        document = await self._document_service.create_document(
            canonical_key=canonical_key,
            title=command.title,
            actor_principal_id=actor_principal_id,
            description=None,
            document_type=None,
            department=None,
            default_language_code=command.language_code,
            metadata={},
        )
        version = await self._version_service.create_version(
            document_id=document.document_id,
            version_label=command.version_label,
            actor_principal_id=actor_principal_id,
            metadata={},
        )
        uploaded = await self._upload_service.upload(
            UploadDocumentArtifact(
                document_id=document.document_id,
                document_version_id=version.version_id,
                artifact_key=command.artifact_key,
                language_code=command.language_code,
                source_name=command.source_name,
                source_uri=None,
                content_type=command.content_type,
                content=command.content,
            ),
            actor_principal_id=actor_principal_id,
        )
        raw_chunking_configuration = (
            command.chunking_configuration or DEFAULT_CHUNKING_CONFIG.as_mapping()
        )
        chunking_config = ChunkingConfig.from_run_configuration(
            {"chunking": raw_chunking_configuration}
        )
        configuration: dict[str, object] = {
            "language_code": command.language_code,
            "chunking": chunking_config.as_mapping(),
        }
        run_id = await self._lifecycle.create_run(
            configuration=configuration,
            configuration_hash=_configuration_hash(configuration),
            created_by_principal_id=actor_principal_id,
        )
        item_id = await self._lifecycle.add_item(
            ingestion_run_id=run_id,
            document_artifact_id=uploaded.artifact_id,
        )
        return QueuedIngestion(
            document_id=document.document_id,
            document_version_id=version.version_id,
            artifact_id=uploaded.artifact_id,
            canonical_key=canonical_key,
            ingestion_run_id=run_id,
            ingestion_item_id=item_id,
            status=IngestionStatus.PENDING,
        )


def _configuration_hash(configuration: Mapping[str, object]) -> str:
    serialized = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_ARTIFACT_KEY",
    "DEFAULT_VERSION_LABEL",
    "IngestDocument",
    "IngestionPipelineService",
    "QueuedIngestion",
]
