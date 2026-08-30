import hashlib
import logging
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atlasrag.contracts.documents import (
    CreateDocumentArtifact,
    KnowledgeUnitOfWork,
    UploadDocumentArtifact,
    UploadedDocumentArtifact,
)
from atlasrag.contracts.error.document_errors import (
    DocumentArtifactConflict,
    DocumentArtifactContentTypeInvalid,
    DocumentArtifactEmpty,
    DocumentArtifactKeyInvalid,
    DocumentArtifactLanguageCodeInvalid,
    DocumentArtifactStorageLocationConflict,
    DocumentArtifactTooLarge,
    DocumentArtifactVersionNotDraft,
    DocumentDeleted,
    DocumentNotFound,
    DocumentVersionNotFound,
)
from atlasrag.contracts.object_storage import ObjectStorage
from atlasrag.contracts.types.authorization_types import DocumentVersionStatus

logger = logging.getLogger(__name__)


class DocumentArtifactUploadService:
    def __init__(
        self,
        uow_factory: Callable[[], KnowledgeUnitOfWork],
        *,
        object_storage: ObjectStorage,
        max_file_size_bytes: int,
        accepted_language_codes: Collection[str],
        allowed_content_types: Collection[str],
        artifact_key_max_length: int,
        language_code_max_length: int,
        storage_provider: str,
        artifact_id_factory: Callable[[], UUID] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_file_size_bytes <= 0:
            raise ValueError("max_file_size_bytes must be greater than zero")
        if not allowed_content_types:
            raise ValueError("allowed_content_types must not be empty")
        if artifact_key_max_length <= 0:
            raise ValueError("artifact_key_max_length must be greater than zero")
        if language_code_max_length <= 0:
            raise ValueError("language_code_max_length must be greater than zero")
        if not storage_provider.strip():
            raise ValueError("storage_provider must not be empty")
        accepted_languages = frozenset(accepted_language_codes)
        if not accepted_languages:
            raise ValueError("accepted_language_codes must not be empty")
        if any(
            not language_code.strip() or len(language_code) > language_code_max_length
            for language_code in accepted_languages
        ):
            raise ValueError(
                "accepted_language_codes must contain non-empty codes within the configured length"
            )

        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._max_file_size_bytes = max_file_size_bytes
        self._accepted_language_codes = accepted_languages
        self._allowed_content_types = frozenset(allowed_content_types)
        self._artifact_key_max_length = artifact_key_max_length
        self._language_code_max_length = language_code_max_length
        self._storage_provider = storage_provider
        self._artifact_id_factory = artifact_id_factory or uuid4
        self._clock = clock or (lambda: datetime.now(UTC))

    async def upload(
        self,
        command: UploadDocumentArtifact,
        *,
        actor_principal_id: UUID,
    ) -> UploadedDocumentArtifact:
        artifact_id = self._artifact_id_factory()
        storage_key = build_storage_key(
            document_id=command.document_id,
            version_id=command.document_version_id,
            artifact_id=artifact_id,
        )
        uploaded = False
        committed = False

        try:
            async with self._uow_factory() as uow:
                await self._validate_target(uow=uow, command=command)
                self._validate_file(command)

                if await uow.document_artifacts.artifact_key_exists(
                    document_version_id=command.document_version_id,
                    artifact_key=command.artifact_key,
                ):
                    raise DocumentArtifactConflict(
                        document_version_id=command.document_version_id,
                        artifact_key=command.artifact_key,
                    )
                if await uow.document_artifacts.storage_key_exists(
                    storage_provider=self._storage_provider,
                    storage_key=storage_key,
                ):
                    raise DocumentArtifactStorageLocationConflict(
                        storage_provider=self._storage_provider,
                        storage_key=storage_key,
                    )

                file_hash = sha256_hex(command.content)
                file_size_bytes = len(command.content)

                await self._object_storage.put(
                    key=storage_key,
                    content=command.content,
                    content_type=command.content_type,
                )
                uploaded = True

                await uow.document_artifacts.add(
                    artifact=CreateDocumentArtifact(
                        artifact_id=artifact_id,
                        document_version_id=command.document_version_id,
                        artifact_key=command.artifact_key,
                        language_code=command.language_code,
                        source_name=command.source_name,
                        source_uri=command.source_uri,
                        source_updated_at=command.source_updated_at,
                        storage_provider=self._storage_provider,
                        storage_key=storage_key,
                        mime_type=command.content_type,
                        file_hash=file_hash,
                        file_size_bytes=file_size_bytes,
                        created_by_principal_id=actor_principal_id,
                        metadata={},
                        created_at=self._clock(),
                    )
                )
                await uow.commit()
                committed = True
        finally:
            if uploaded and not committed:
                await self._best_effort_delete(storage_key)

        return UploadedDocumentArtifact(
            artifact_id=artifact_id,
            document_version_id=command.document_version_id,
            artifact_key=command.artifact_key,
            language_code=command.language_code,
            mime_type=command.content_type,
            file_hash=file_hash,
            file_size_bytes=file_size_bytes,
        )

    async def _validate_target(
        self,
        *,
        uow: KnowledgeUnitOfWork,
        command: UploadDocumentArtifact,
    ) -> None:
        document = await uow.documents.find_by_id(
            document_id=command.document_id,
            lock=True,
        )
        if document is None:
            raise DocumentNotFound(document_id=command.document_id)
        if document.deleted_at is not None:
            raise DocumentDeleted(document_id=command.document_id)

        version = await uow.document_versions.find_by_id(
            document_id=command.document_id,
            version_id=command.document_version_id,
            lock=True,
        )
        if version is None:
            raise DocumentVersionNotFound(
                document_id=command.document_id,
                version_id=command.document_version_id,
            )
        if version.status is not DocumentVersionStatus.DRAFT:
            raise DocumentArtifactVersionNotDraft(
                document_version_id=command.document_version_id,
                status=version.status,
            )

    def _validate_file(self, command: UploadDocumentArtifact) -> None:
        if (
            not command.artifact_key.strip()
            or len(command.artifact_key) > self._artifact_key_max_length
        ):
            raise DocumentArtifactKeyInvalid(artifact_key=command.artifact_key)
        if len(command.language_code) > self._language_code_max_length:
            raise DocumentArtifactLanguageCodeInvalid(language_code=command.language_code)
        if command.language_code not in self._accepted_language_codes:
            raise DocumentArtifactLanguageCodeInvalid(language_code=command.language_code)
        if command.content_type not in self._allowed_content_types:
            raise DocumentArtifactContentTypeInvalid(content_type=command.content_type)
        if not command.content:
            raise DocumentArtifactEmpty()
        if len(command.content) > self._max_file_size_bytes:
            raise DocumentArtifactTooLarge(
                file_size_bytes=len(command.content),
                max_file_size_bytes=self._max_file_size_bytes,
            )

    async def _best_effort_delete(self, storage_key: str) -> None:
        try:
            await self._object_storage.delete(key=storage_key)
        except Exception:
            logger.exception(
                "Failed to compensate document artifact upload",
                extra={"storage_key": storage_key},
            )


def build_storage_key(
    *,
    document_id: UUID,
    version_id: UUID,
    artifact_id: UUID,
) -> str:
    return f"documents/{document_id}/versions/{version_id}/artifacts/{artifact_id}"


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = [
    "DocumentArtifactUploadService",
    "build_storage_key",
    "sha256_hex",
]
