import hashlib
from uuid import UUID

from atlasrag.contracts.documents import DocumentArtifactRepository
from atlasrag.contracts.object_storage import ObjectStorage
from atlasrag.contracts.types.authorization import DocumentArtifactStatus
from atlasrag.contracts.types.document import DocumentArtifactState
from atlasrag.contracts.types.ingestion import LoadedArtifact
from atlasrag.contracts.types.observability import (
    JobStage,
    MetricName,
    SpanName,
)
from atlasrag.platform.observability import (
    annotate_span,
    traced_stage,
    traced_stage_sync,
    update_job_context,
)


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
        async with traced_stage(
            SpanName.ARTIFACT_LOAD,
            stage=JobStage.ARTIFACT_LOAD,
            duration_metric=MetricName.ARTIFACT_LOAD_DURATION_SECONDS,
        ) as observation:
            artifact = await self._artifact_repository.find_for_ingestion(artifact_id=artifact_id)
            if artifact is None or artifact.status is not DocumentArtifactStatus.AVAILABLE:
                raise ArtifactUnavailableForIngestion(
                    artifact_id=artifact_id,
                    status=artifact.status if artifact is not None else None,
                )

            update_job_context(
                artifact_id=artifact.artifact_id,
                language_code=artifact.language_code,
            )
            annotate_span(
                observation.span,
                mime_type=artifact.mime_type,
                expected_file_size_bytes=artifact.file_size_bytes,
            )

            content = await self._object_storage.get(key=artifact.storage_key)
            observed_file_hash = self._verify_integrity(artifact_state=artifact, content=content)

            return LoadedArtifact(
                artifact_id=artifact.artifact_id,
                content=content,
                mime_type=artifact.mime_type,
                expected_file_hash=artifact.file_hash,
                observed_file_hash=observed_file_hash,
                file_size_bytes=artifact.file_size_bytes,
            )

    def _verify_integrity(
        self,
        *,
        artifact_state: DocumentArtifactState,
        content: bytes,
    ) -> str:
        with traced_stage_sync(
            SpanName.ARTIFACT_INTEGRITY,
            stage=JobStage.ARTIFACT_INTEGRITY,
        ) as observation:
            observed_file_hash = hashlib.sha256(content).hexdigest()
            observed_file_size_bytes = len(content)
            annotate_span(observation.span, observed_file_size_bytes=observed_file_size_bytes)
            if (
                observed_file_size_bytes != artifact_state.file_size_bytes
                or observed_file_hash != artifact_state.file_hash
            ):
                raise ArtifactIntegrityMismatch(
                    artifact_id=artifact_state.artifact_id,
                    expected_file_hash=artifact_state.file_hash,
                    observed_file_hash=observed_file_hash,
                    expected_file_size_bytes=artifact_state.file_size_bytes,
                    observed_file_size_bytes=observed_file_size_bytes,
                )
            return observed_file_hash


__all__ = [
    "ArtifactIntegrityMismatch",
    "ArtifactLoadError",
    "ArtifactLoader",
    "ArtifactUnavailableForIngestion",
]
