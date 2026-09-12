import uuid

from sqlalchemy import insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.types.ai_types import AiProvider
from atlasrag.contracts.types.embedding import (
    EmbeddingModelIdentity,
    EmbeddingModelState,
    VectorDistanceMetric,
)
from atlasrag.modules.embedding.models import EmbeddingModel


def _model_columns() -> tuple[object, ...]:
    return (
        EmbeddingModel.id,
        EmbeddingModel.provider,
        EmbeddingModel.model_name,
        EmbeddingModel.model_revision,
        EmbeddingModel.dimension,
        EmbeddingModel.distance_metric,
        EmbeddingModel.max_input_tokens,
        EmbeddingModel.configuration,
        EmbeddingModel.configuration_hash,
        EmbeddingModel.created_at,
    )


def _to_model_state(row: Row) -> EmbeddingModelState:
    return EmbeddingModelState(
        id=row.id,
        provider=AiProvider(row.provider),
        model_name=row.model_name,
        model_revision=row.model_revision,
        dimension=row.dimension,
        distance_metric=VectorDistanceMetric(row.distance_metric),
        max_input_tokens=row.max_input_tokens,
        configuration=row.configuration,
        configuration_hash=row.configuration_hash,
        created_at=row.created_at,
    )


class EmbeddingModelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_model(
        self,
        *,
        model_id: uuid.UUID,
        identity: EmbeddingModelIdentity,
        configuration_hash: str,
    ) -> None:
        await self._session.execute(
            insert(EmbeddingModel).values(
                id=model_id,
                provider=identity.provider.value,
                model_name=identity.model_name,
                model_revision=identity.model_revision,
                dimension=identity.dimension,
                distance_metric=identity.distance_metric,
                max_input_tokens=identity.max_input_tokens,
                configuration=dict(identity.configuration),
                configuration_hash=configuration_hash,
            )
        )
        return None

    async def find_model(self, *, model_id: uuid.UUID) -> EmbeddingModelState | None:
        statement = select(*_model_columns()).where(EmbeddingModel.id == model_id)
        row = (await self._session.execute(statement)).one_or_none()
        return _to_model_state(row) if row is not None else None

    async def find_model_by_identity(
        self,
        *,
        provider: str,
        model_name: str,
        model_revision: str,
        configuration_hash: str,
    ) -> EmbeddingModelState | None:
        statement = select(*_model_columns()).where(
            EmbeddingModel.provider == provider,
            EmbeddingModel.model_name == model_name,
            EmbeddingModel.model_revision == model_revision,
            EmbeddingModel.configuration_hash == configuration_hash,
        )
        row = (await self._session.execute(statement)).one_or_none()
        return _to_model_state(row) if row is not None else None

__all__ = ["EmbeddingModelRepository"]
