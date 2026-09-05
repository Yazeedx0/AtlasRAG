import hashlib
from uuid import UUID

from atlasrag.contracts.documents import DocumentArtifactRepository
from atlasrag.contracts.object_storage import ObjectStorage
from atlasrag.contracts.types.authorization import DocumentArtifactStatus
from atlasrag.contracts.types.ingestion import LoadedArtifact


class ArtifactLoadError(Exception):
    """Base error raised while preparing an artifact for ingestion."""


class ArtifactUnavailableForIngestion(ArtifactLoadError):
    def __init__(
        self,
        *,
        artifact_id: UUID,
        status: DocumentArtifactStatus | None,
    ) -> None:
        self.artifact_id = artifact_id
        self.status = status
        if status is None:
            message = f"Artifact {artifact_id} does not exist."
        else:
            message = f"Artifact {artifact_id} is {status.value}, not available."
        super().__init__(message)


class ArtifactIntegrityMismatch(ArtifactLoadError):
    def __init__(
        self,
        *,
        artifact_id: UUID,
        expected_file_hash: str,
        observed_file_hash: str,
        expected_file_size_bytes: int,
        observed_file_size_bytes: int,
    ) -> None:
        self.artifact_id = artifact_id
        self.expected_file_hash = expected_file_hash
        self.observed_file_hash = observed_file_hash
        self.expected_file_size_bytes = expected_file_size_bytes
        self.observed_file_size_bytes = observed_file_size_bytes
        super().__init__(
            f"Artifact {artifact_id} content does not match its recorded integrity."
        )


class ArtifactLoader:
    def __init__(
        self,
        *,
        artifact_repository: DocumentArtifactRepository,
        object_storage: ObjectStorage,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._object_storage = object_storage

    async def load(self, *, artifact_id: UUID) -> LoadedArtifact:
        artifact = await self._artifact_repository.find_for_ingestion(artifact_id=artifact_id)
        if artifact is None or artifact.status is not DocumentArtifactStatus.AVAILABLE:
            raise ArtifactUnavailableForIngestion(
                artifact_id=artifact_id,
                status=artifact.status if artifact is not None else None,
            )

        content = await self._object_storage.get(key=artifact.storage_key)
        observed_file_hash = hashlib.sha256(content).hexdigest()
        observed_file_size_bytes = len(content)
        if (
            observed_file_size_bytes != artifact.file_size_bytes
            or observed_file_hash != artifact.file_hash
        ):
            raise ArtifactIntegrityMismatch(
                artifact_id=artifact.artifact_id,
                expected_file_hash=artifact.file_hash,
                observed_file_hash=observed_file_hash,
                expected_file_size_bytes=artifact.file_size_bytes,
                observed_file_size_bytes=observed_file_size_bytes,
            )

        return LoadedArtifact(
            artifact_id=artifact.artifact_id,
            content=content,
            mime_type=artifact.mime_type,
            expected_file_hash=artifact.file_hash,
            observed_file_hash=observed_file_hash,
            file_size_bytes=artifact.file_size_bytes,
        )


__all__ = [
    "ArtifactIntegrityMismatch",
    "ArtifactLoadError",
    "ArtifactLoader",
    "ArtifactUnavailableForIngestion",
]
