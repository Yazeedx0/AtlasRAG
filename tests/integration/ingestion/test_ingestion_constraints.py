from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types import IngestionStatus
from atlasrag.modules.ingestion.models import IngestionItem, IngestionRun
from atlasrag.modules.knowledge.models import (
    Document,
    DocumentArtifact,
    DocumentVersion,
)
from atlasrag.platform.database.integrity import is_integrity_error_for_constraint

CLAIMED_AT = datetime(2026, 9, 1, 12, tzinfo=UTC)
LEASE_EXPIRES_AT = CLAIMED_AT + timedelta(minutes=5)
COMPLETED_AT = CLAIMED_AT + timedelta(minutes=1)

ATTEMPT_COUNT_NON_NEGATIVE = "ck_ingestion_items_attempt_count_non_negative"
RUNNING_REQUIRES_CLAIM = "ck_ingestion_items_running_requires_claim"
LEASE_ONLY_WHILE_RUNNING = "ck_ingestion_items_lease_only_while_running"
VALID_LEASE = "ck_ingestion_items_valid_lease"
TERMINAL_REQUIRES_COMPLETED_AT = "ck_ingestion_items_terminal_requires_completed_at"
COMPLETED_NOT_BEFORE_STARTED = "ck_ingestion_items_completed_not_before_started"
ACTIVATION_REQUIRES_COMPLETION = "ck_ingestion_items_activation_requires_completion"
DEACTIVATION_AFTER_ACTIVATION = "ck_ingestion_items_deactivation_after_activation"
UNIQUE_RUN_ARTIFACT = "uq_ingestion_items_run_artifact"
UNIQUE_ACTIVE_ARTIFACT = "uq_ingestion_items_active_artifact"


async def add_artifact(session: AsyncSession) -> UUID:
    document_id = uuid4()
    version_id = uuid4()
    artifact_id = uuid4()

    await session.execute(
        Document.__table__.insert().values(
            id=document_id,
            canonical_key=f"canonical-{document_id}",
            title="Ingestion constraint fixture",
        )
    )
    await session.execute(
        DocumentVersion.__table__.insert().values(
            id=version_id,
            document_id=document_id,
            version_label="v1",
        )
    )
    await session.execute(
        DocumentArtifact.__table__.insert().values(
            id=artifact_id,
            document_version_id=version_id,
            artifact_key=f"artifact-{artifact_id}",
            language_code="en",
            source_name="fixture.pdf",
            storage_provider="s3",
            storage_key=f"key/{artifact_id}",
            mime_type="application/pdf",
            file_hash="a" * 64,
            file_size_bytes=1024,
        )
    )
    return artifact_id


async def add_run(session: AsyncSession) -> UUID:
    run_id = uuid4()
    await session.execute(
        IngestionRun.__table__.insert().values(
            id=run_id,
            configuration_hash="b" * 64,
        )
    )
    return run_id


async def insert_item(
    session: AsyncSession,
    *,
    run_id: UUID,
    artifact_id: UUID,
    **values: object,
) -> UUID:
    item_id = uuid4()
    await session.execute(
        IngestionItem.__table__.insert().values(
            id=item_id,
            ingestion_run_id=run_id,
            document_artifact_id=artifact_id,
            **values,
        )
    )
    return item_id


@pytest.mark.asyncio
async def test_pending_item_is_accepted(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)
        await insert_item(
            session,
            run_id=run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.PENDING,
        )
        await session.commit()


@pytest.mark.asyncio
async def test_running_item_with_full_lease_is_accepted(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)
        await insert_item(
            session,
            run_id=run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.RUNNING,
            started_at=CLAIMED_AT,
            claimed_at=CLAIMED_AT,
            lease_expires_at=LEASE_EXPIRES_AT,
        )
        await session.commit()


@pytest.mark.asyncio
async def test_completed_item_with_activation_is_accepted(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)
        await insert_item(
            session,
            run_id=run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.COMPLETED,
            started_at=CLAIMED_AT,
            completed_at=COMPLETED_AT,
            activated_at=COMPLETED_AT,
        )
        await session.commit()


@pytest.mark.asyncio
async def test_negative_attempt_count_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.PENDING,
                attempt_count=-1,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=ATTEMPT_COUNT_NON_NEGATIVE,
    )


@pytest.mark.asyncio
async def test_running_without_claim_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.RUNNING,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=RUNNING_REQUIRES_CLAIM,
    )


@pytest.mark.asyncio
async def test_lease_on_pending_item_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.PENDING,
                claimed_at=CLAIMED_AT,
                lease_expires_at=LEASE_EXPIRES_AT,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=LEASE_ONLY_WHILE_RUNNING,
    )


@pytest.mark.asyncio
async def test_lease_expiring_before_claim_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.RUNNING,
                started_at=CLAIMED_AT,
                claimed_at=CLAIMED_AT,
                lease_expires_at=CLAIMED_AT,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=VALID_LEASE,
    )


@pytest.mark.asyncio
async def test_completed_without_completed_at_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.COMPLETED,
                started_at=CLAIMED_AT,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=TERMINAL_REQUIRES_COMPLETED_AT,
    )


@pytest.mark.asyncio
async def test_failed_without_completed_at_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.FAILED,
                started_at=CLAIMED_AT,
                error_code="extraction_failed",
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=TERMINAL_REQUIRES_COMPLETED_AT,
    )


@pytest.mark.asyncio
async def test_completion_before_start_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.COMPLETED,
                started_at=COMPLETED_AT,
                completed_at=CLAIMED_AT,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=COMPLETED_NOT_BEFORE_STARTED,
    )


@pytest.mark.asyncio
async def test_activation_without_completion_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.PENDING,
                activated_at=COMPLETED_AT,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=ACTIVATION_REQUIRES_COMPLETION,
    )


@pytest.mark.asyncio
async def test_deactivation_without_activation_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.COMPLETED,
                started_at=CLAIMED_AT,
                completed_at=COMPLETED_AT,
                deactivated_at=COMPLETED_AT,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=DEACTIVATION_AFTER_ACTIVATION,
    )


@pytest.mark.asyncio
async def test_duplicate_artifact_in_same_run_is_rejected(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)
        await insert_item(
            session,
            run_id=run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.PENDING,
        )

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.PENDING,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=UNIQUE_RUN_ARTIFACT,
    )


@pytest.mark.asyncio
async def test_same_artifact_in_different_runs_is_accepted(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        first_run_id = await add_run(session)
        second_run_id = await add_run(session)

        await insert_item(
            session,
            run_id=first_run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.PENDING,
        )
        await insert_item(
            session,
            run_id=second_run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.PENDING,
        )
        await session.commit()


@pytest.mark.asyncio
async def test_two_active_items_for_one_artifact_are_rejected(
    identity_database,
) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        first_run_id = await add_run(session)
        second_run_id = await add_run(session)

        await insert_item(
            session,
            run_id=first_run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.COMPLETED,
            started_at=CLAIMED_AT,
            completed_at=COMPLETED_AT,
            activated_at=COMPLETED_AT,
        )

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=second_run_id,
                artifact_id=artifact_id,
                status=IngestionStatus.COMPLETED,
                started_at=CLAIMED_AT,
                completed_at=COMPLETED_AT,
                activated_at=COMPLETED_AT,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name=UNIQUE_ACTIVE_ARTIFACT,
    )


@pytest.mark.asyncio
async def test_reactivation_after_deactivation_is_accepted(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        first_run_id = await add_run(session)
        second_run_id = await add_run(session)

        await insert_item(
            session,
            run_id=first_run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.COMPLETED,
            started_at=CLAIMED_AT,
            completed_at=COMPLETED_AT,
            activated_at=COMPLETED_AT,
            deactivated_at=COMPLETED_AT + timedelta(hours=1),
        )
        await insert_item(
            session,
            run_id=second_run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.COMPLETED,
            started_at=CLAIMED_AT,
            completed_at=COMPLETED_AT,
            activated_at=COMPLETED_AT + timedelta(hours=2),
        )
        await session.commit()


@pytest.mark.asyncio
async def test_item_requires_existing_run(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)

        with pytest.raises(IntegrityError) as error:
            await insert_item(
                session,
                run_id=uuid4(),
                artifact_id=artifact_id,
                status=IngestionStatus.PENDING,
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name="fk_ingestion_items_ingestion_run_id_ingestion_runs",
    )


@pytest.mark.asyncio
async def test_run_with_items_cannot_be_deleted(identity_database) -> None:
    _, session_factory = identity_database

    async with session_factory() as session:
        artifact_id = await add_artifact(session)
        run_id = await add_run(session)
        await insert_item(
            session,
            run_id=run_id,
            artifact_id=artifact_id,
            status=IngestionStatus.PENDING,
        )
        await session.commit()

        with pytest.raises(IntegrityError) as error:
            await session.execute(
                IngestionRun.__table__.delete().where(
                    IngestionRun.__table__.c.id == run_id
                )
            )

    assert is_integrity_error_for_constraint(
        error=error.value,
        constraint_name="fk_ingestion_items_ingestion_run_id_ingestion_runs",
    )
