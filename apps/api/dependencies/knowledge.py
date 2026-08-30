from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.contracts.documents import (
    DocumentAclRepository,
    DocumentRepository,
)
from atlasrag.contracts.identity import PrincipalRepository
from atlasrag.modules.identity.repositories.principal import SqlAlchemyPrincipalRepository
from atlasrag.modules.knowledge.repositories.document_acl_repository import (
    SqlAlchemyDocumentAclRepository,
)
from atlasrag.modules.knowledge.repositories.document_repository import (
    SqlAlchemyDocumentRepository,
)
from atlasrag.modules.knowledge.services.document_acl_management import (
    DocumentAclManagementService,
)
from atlasrag.modules.knowledge.services.document_management import (
    DocumentManagementService,
)
from atlasrag.platform.database.session import async_session_factory


class SqlAlchemyKnowledgeUnitOfWork:
    documents: DocumentRepository
    acl: DocumentAclRepository
    principals: PrincipalRepository

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "SqlAlchemyKnowledgeUnitOfWork":
        self._session = self._session_factory()
        self.documents = SqlAlchemyDocumentRepository(self._session)
        self.acl = SqlAlchemyDocumentAclRepository(self._session)
        self.principals = SqlAlchemyPrincipalRepository(self._session)
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
) -> Callable[[], SqlAlchemyKnowledgeUnitOfWork]:
    def factory() -> SqlAlchemyKnowledgeUnitOfWork:
        return SqlAlchemyKnowledgeUnitOfWork(session_factory)

    return factory


def get_document_management_service() -> DocumentManagementService:
    return DocumentManagementService(
        make_knowledge_unit_of_work_factory(async_session_factory),
    )


def get_document_acl_management_service() -> DocumentAclManagementService:
    return DocumentAclManagementService(
        make_knowledge_unit_of_work_factory(async_session_factory),
    )


__all__ = [
    "get_document_acl_management_service",
    "get_document_management_service",
    "make_knowledge_unit_of_work_factory",
]
