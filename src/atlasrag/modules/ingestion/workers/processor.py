from typing import Protocol

from atlasrag.contracts.types.ingestion import ClaimedIngestionItem


class IngestionProcessor(Protocol):
    async def process(
        self,
        *,
        claim: ClaimedIngestionItem,
    ) -> None:
        ...


__all__ = ["IngestionProcessor"]