from uuid import UUID

from atlasrag.contracts.identity import EffectivePrincipalRepository


class EffectivePrincipalResolver:
    def __init__(self, repository: EffectivePrincipalRepository) -> None:
        self._repository = repository

    async def resolve_effective_principal_ids(
        self,
        user_principal_id: UUID,
    ) -> frozenset[UUID]:
        return await self._repository.find_effective_principal_ids(user_principal_id)
