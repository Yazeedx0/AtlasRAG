import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atlasrag.contracts.types.authorization import DocumentArtifactStatus, DocumentVersionStatus
from atlasrag.modules.ingestion.services.artifact_loader import (
    ArtifactIntegrityMismatch,
    ArtifactLoader,
)
from atlasrag.modules.knowledge.models import Document, DocumentArtifact, DocumentVersion
from atlasrag.modules.knowledge.repositories.document_artifact import (
    DocumentArtifactRepository,
)
from atlasrag.platform.storage import MinioObjectStorage


async def add_artifact(
    session: AsyncSession,
    *,
    expected_content: bytes,
) -> tuple[UUID, str]:
    document_id = uuid4()
    version_id = uuid4()
    artifact_id = uuid4()
    storage_key = f"documents/{document_id}/versions/{version_id}/artifacts/{artifact_id}"

    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"artifact-loader-{document_id}",
            title="Artifact loader integration document",
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
    await session.execute(
        DocumentArtifact.__table__.insert().values(
            id=artifact_id,
            document_version_id=version_id,
            artifact_key="source",
            language_code="en",
            source_name="source.txt",
            storage_provider="s3",
            storage_key=storage_key,
            mime_type="text/plain",
            file_hash=hashlib.sha256(expected_content).hexdigest(),
            file_size_bytes=len(expected_content),
            status=DocumentArtifactStatus.AVAILABLE,
        )
    )
    return artifact_id, storage_key


@pytest.mark.integration
@pytest.mark.asyncio
async def test_loader_returns_bytes_verified_against_postgres_metadata_and_minio(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    minio_object_storage: MinioObjectStorage,
) -> None:
    _, session_factory = identity_database
    content = b"AtlasRAG verified artifact"

    async with session_factory() as session:
        artifact_id, storage_key = await add_artifact(session, expected_content=content)
        await session.commit()

    await minio_object_storage.put(
        key=storage_key,
        content=content,
        content_type="text/plain",
    )

    async with session_factory() as session:
        loader = ArtifactLoader(
            artifact_repository=DocumentArtifactRepository(session),
            object_storage=minio_object_storage,
        )
        loaded = await loader.load(artifact_id=artifact_id)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert loaded.artifact_id == artifact_id
    assert loaded.content == content
    assert loaded.mime_type == "text/plain"
    assert loaded.expected_file_hash == expected_hash
    assert loaded.observed_file_hash == expected_hash
    assert loaded.file_size_bytes == len(content)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_loader_rejects_minio_bytes_that_do_not_match_postgres_hash(
    identity_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    minio_object_storage: MinioObjectStorage,
) -> None:
    _, session_factory = identity_database
    expected_content = b"expected artifact bytes"
    observed_content = b"different artifact bytes"

    async with session_factory() as session:
        artifact_id, storage_key = await add_artifact(
            session,
            expected_content=expected_content,
        )
        await session.commit()

    await minio_object_storage.put(
        key=storage_key,
        content=observed_content,
        content_type="text/plain",
    )

    async with session_factory() as session:
        loader = ArtifactLoader(
            artifact_repository=DocumentArtifactRepository(session),
            object_storage=minio_object_storage,
        )
        with pytest.raises(ArtifactIntegrityMismatch) as error:
            await loader.load(artifact_id=artifact_id)

    assert error.value.expected_file_hash == hashlib.sha256(expected_content).hexdigest()
    assert error.value.observed_file_hash == hashlib.sha256(observed_content).hexdigest()
