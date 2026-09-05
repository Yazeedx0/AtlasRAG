from atlasrag.contracts.error.object_storage_errors import (
    ObjectNotFound,
    ObjectStorageUnavailable,
)
from atlasrag.contracts.types.ingestion import ClaimedIngestionItem
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactLoader,
    ArtifactUnavailableForIngestion,
)
from atlasrag.modules.ingestion.workers.errors import (
    PermanentIngestionError,
    TransientIngestionError,
)


class DefaultIngestionProcessor:
    def __init__(self, *, artifact_loader: ArtifactLoader) -> None:
        self._artifact_loader = artifact_loader

    async def process(self, *, claim: ClaimedIngestionItem) -> None:
        try:
            await self._artifact_loader.load(artifact_id=claim.document_artifact_id)
        except ArtifactUnavailableForIngestion as error:
            raise PermanentIngestionError(
                error_code="artifact_unavailable_for_ingestion",
            ) from error
        except ArtifactIntegrityMismatch as error:
            raise PermanentIngestionError(
                error_code="artifact_integrity_mismatch",
            ) from error
        except ObjectNotFound as error:
            raise PermanentIngestionError(
                error_code="artifact_object_missing",
            ) from error
        except ObjectStorageUnavailable as error:
            raise TransientIngestionError("Object storage is temporarily unavailable.") from error


__all__ = ["DefaultIngestionProcessor"]
