from collections.abc import Collection
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from atlasrag.modules.knowledge.services.document_authorization import (
    DocumentAuthorizationService,
)


class FakeDocumentAccessRepository:
    def __init__(self, result: bool) -> None:
        self._result = result
        self.calls: list[tuple[UUID, Collection[UUID], datetime]] = []

    async def has_active_read_grant(
        self,
        *,
        document_id: UUID,
        principal_ids: Collection[UUID],
        at: datetime,
    ) -> bool:
        self.calls.append((document_id, principal_ids, at))
        return self._result


@pytest.mark.asyncio
async def test_can_read_document_denies_empty_effective_principals_without_query() -> None:
    repository = FakeDocumentAccessRepository(result=True)
    service = DocumentAuthorizationService(repository)

    result = await service.can_read_document(
        document_id=uuid4(),
        effective_principal_ids=frozenset(),
        at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert result is False
    assert repository.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_result", [True, False])
async def test_can_read_document_returns_repository_decision(
    repository_result: bool,
) -> None:
    document_id = uuid4()
    principal_ids = frozenset({uuid4(), uuid4()})
    evaluated_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    repository = FakeDocumentAccessRepository(result=repository_result)
    service = DocumentAuthorizationService(repository)

    result = await service.can_read_document(
        document_id=document_id,
        effective_principal_ids=principal_ids,
        at=evaluated_at,
    )

    assert result is repository_result
    assert repository.calls == [(document_id, principal_ids, evaluated_at)]
