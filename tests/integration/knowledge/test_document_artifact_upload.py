import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from apps.api.dependencies.knowledge import make_knowledge_unit_of_work_factory
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atlasrag.contracts.documents import CreateDocumentArtifact, UploadDocumentArtifact
from atlasrag.contracts.error.document_errors import DocumentArtifactConflict
from atlasrag.contracts.types.authorization import DocumentVersionStatus
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import Principal, Users
from atlasrag.modules.knowledge.models import Document, DocumentArtifact, DocumentVersion
from atlasrag.modules.knowledge.repositories.document_artifact import (
    DocumentArtifactRepository,
)
from atlasrag.modules.knowledge.services.document_artifact_upload import (
    DocumentArtifactUploadService,
)
from atlasrag.platform.storage import MinioObjectStorage


async def add_user(session: AsyncSession, *, principal_id: UUID) -> None:
    await session.execute(
        Principal.__table__.insert().values(
            id=principal_id,
            type=PrincipalType.USER,
        )
    )
    await session.execute(
        Users.__table__.insert().values(
            principal_id=principal_id,
            display_name=str(principal_id),
        )
    )


async def add_document_and_version(
    session: AsyncSession,
    *,
    document_id: UUID,
    version_id: UUID,
) -> None:
    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"document-{document_id}",
            title="Artifact integration document",
        )
    )
    await session.execute(
        DocumentVersion.__table__.insert().values(
            id=version_id,
            document_id=document_id,
            version_label="v1",
            status=DocumentVersionStatus.DRAFT,
        )
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_persists_matching_postgres_row_and_minio_object(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    minio_object_storage: MinioObjectStorage,
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    version_id = uuid4()
    actor_id = uuid4()
    content = b"AtlasRAG artifact integration content"
    source_updated_at = datetime(2026, 8, 30, tzinfo=UTC)

    async with session_factory() as session:
        await add_user(session, principal_id=actor_id)
        await add_document_and_version(
            session,
            document_id=document_id,
            version_id=version_id,
        )
        await session.commit()

    service = DocumentArtifactUploadService(
        make_knowledge_unit_of_work_factory(session_factory),
        object_storage=minio_object_storage,
        max_file_size_bytes=1024 * 1024,
        accepted_language_codes={"ar", "en"},
        allowed_content_types={
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/html",
            "text/markdown",
            "text/plain",
        },
        artifact_key_max_length=255,
        language_code_max_length=20,
        storage_provider="s3",
    )
    result = await service.upload(
        UploadDocumentArtifact(
            document_id=document_id,
            document_version_id=version_id,
            artifact_key="primary-source",
            language_code="en",
            source_name="source.txt",
            source_uri="https://example.test/source.txt",
            source_updated_at=source_updated_at,
            content_type="text/plain",
            content=content,
        ),
        actor_principal_id=actor_id,
    )

    async with session_factory() as session:
        artifact = await session.scalar(
            select(DocumentArtifact).where(DocumentArtifact.id == result.artifact_id)
        )

    assert artifact is not None
    assert artifact.document_version_id == version_id
    assert artifact.artifact_key == "primary-source"
    assert artifact.storage_provider == "s3"
    assert artifact.storage_key == (
        f"documents/{document_id}/versions/{version_id}/artifacts/{result.artifact_id}"
    )
    assert artifact.file_hash == hashlib.sha256(content).hexdigest()
    assert artifact.file_size_bytes == len(content)
    assert artifact.created_by_principal_id == actor_id
    assert await minio_object_storage.exists(key=artifact.storage_key) is True
    assert await minio_object_storage.get(key=artifact.storage_key) == content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_maps_duplicate_artifact_key_integrity_error_to_domain_conflict(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, session_factory = identity_database
    document_id = uuid4()
    version_id = uuid4()
    created_at = datetime(2026, 8, 30, tzinfo=UTC)

    async with session_factory() as session:
        await add_document_and_version(
            session,
            document_id=document_id,
            version_id=version_id,
        )
        await session.commit()

    async with session_factory() as session:
        repository = DocumentArtifactRepository(session)
        await repository.add(
            artifact=CreateDocumentArtifact(
                artifact_id=uuid4(),
                document_version_id=version_id,
                artifact_key="primary-source",
                language_code="en",
                source_name="first.txt",
                source_uri=None,
                source_updated_at=None,
                storage_provider="s3",
                storage_key=f"objects/{uuid4()}",
                mime_type="text/plain",
                file_hash="a" * 64,
                file_size_bytes=1,
                created_by_principal_id=None,
                metadata={},
                created_at=created_at,
            )
        )

        with pytest.raises(DocumentArtifactConflict) as error:
            await repository.add(
                artifact=CreateDocumentArtifact(
                    artifact_id=uuid4(),
                    document_version_id=version_id,
                    artifact_key="primary-source",
                    language_code="en",
                    source_name="second.txt",
                    source_uri=None,
                    source_updated_at=None,
                    storage_provider="s3",
                    storage_key=f"objects/{uuid4()}",
                    mime_type="text/plain",
                    file_hash="b" * 64,
                    file_size_bytes=1,
                    created_by_principal_id=None,
                    metadata={},
                    created_at=created_at,
                )
            )

        assert isinstance(error.value.__cause__, IntegrityError)
