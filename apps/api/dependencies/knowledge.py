from collections.abc import Callable
from types import TracebackType
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.dependencies.storage import get_object_storage
from atlasrag.bootstrap.core.config import get_settings
from atlasrag.contracts.documents import (
    DocumentAclRepository as DocumentAclRepositoryContract,
    DocumentArtifactRepository as DocumentArtifactRepositoryContract,
    DocumentRepository as DocumentRepositoryContract,
    DocumentVersionRepository as DocumentVersionRepositoryContract,
)
from atlasrag.contracts.identity import PrincipalRepository as PrincipalRepositoryContract
from atlasrag.contracts.object_storage import ObjectStorage
from atlasrag.modules.identity.repositories.principal import PrincipalRepository
from atlasrag.modules.knowledge.repositories.document_acl import (
    DocumentAclRepository,
)
from atlasrag.modules.knowledge.repositories.document import (
    DocumentRepository,
)
from atlasrag.modules.knowledge.repositories.document_artifact import (
    DocumentArtifactRepository,
)
from atlasrag.modules.knowledge.repositories.document_version import (
    DocumentVersionRepository,
)
from atlasrag.modules.knowledge.services.document_acl_management import (
    DocumentAclManagementService,
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


class KnowledgeUnitOfWork:
    documents: DocumentRepositoryContract
    acl: DocumentAclRepositoryContract
    document_versions: DocumentVersionRepositoryContract
    document_artifacts: DocumentArtifactRepositoryContract
    principals: PrincipalRepositoryContract

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "KnowledgeUnitOfWork":
        self._session = self._session_factory()
        self.documents = DocumentRepository(self._session)
        self.acl = DocumentAclRepository(self._session)
        self.document_versions = DocumentVersionRepository(self._session)
        self.document_artifacts = DocumentArtifactRepository(self._session)
        self.principals = PrincipalRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Knowledge unit of work is not active")

        try:
            if exc_type is not None or session.in_transaction():
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._session
        if session is None:
            raise RuntimeError("Knowledge unit of work is not active")
        await session.commit()


def make_knowledge_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], KnowledgeUnitOfWork]:
    def factory() -> KnowledgeUnitOfWork:
        return KnowledgeUnitOfWork(session_factory)

    return factory


def get_document_management_service() -> DocumentManagementService:
    return DocumentManagementService(
        make_knowledge_unit_of_work_factory(async_session_factory),
    )


def get_document_acl_management_service() -> DocumentAclManagementService:
    return DocumentAclManagementService(
        make_knowledge_unit_of_work_factory(async_session_factory),
    )


def get_document_version_management_service() -> DocumentVersionManagementService:
    return DocumentVersionManagementService(
        make_knowledge_unit_of_work_factory(async_session_factory),
    )


def get_document_artifact_upload_service(
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> DocumentArtifactUploadService:
    settings = get_settings()
    return DocumentArtifactUploadService(
        make_knowledge_unit_of_work_factory(async_session_factory),
        object_storage=object_storage,
        max_file_size_bytes=settings.MAX_FILE_SIZE_BYTES,
        accepted_language_codes=settings.ACCEPTED_LANGUAGE_CODES,
        allowed_content_types=settings.ALLOWED_CONTENT_TYPES,
        artifact_key_max_length=settings.ARTIFACT_KEY_MAX_LENGTH,
        language_code_max_length=settings.LANGUAGE_CODE_MAX_LENGTH,
        storage_provider=settings.STORAGE_PROVIDER,
    )


def get_document_artifact_max_file_size_bytes() -> int:
    return get_settings().MAX_FILE_SIZE_BYTES


__all__ = [
    "get_document_acl_management_service",
    "get_document_artifact_max_file_size_bytes",
    "get_document_artifact_upload_service",
    "get_document_management_service",
    "get_document_version_management_service",
    "make_knowledge_unit_of_work_factory",
]
