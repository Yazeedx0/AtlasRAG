import uuid
from collections.abc import Callable

from atlasrag.contracts.embedding import EmbeddingUnitOfWork
from atlasrag.contracts.types.embedding import EmbeddingModelIdentity, EmbeddingModelState
from atlasrag.platform.configuration_hash import canonical_configuration_hash


class EmbeddingModelRegistryService:
    def __init__(self, uow_factory: Callable[[], EmbeddingUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def register(self, *, identity: EmbeddingModelIdentity) -> uuid.UUID:
        configuration_hash = canonical_configuration_hash(dict(identity.configuration))
        async with self._uow_factory() as uow:
            existing = await uow.models.find_model_by_identity(
                provider=identity.provider.value,
                model_name=identity.model_name,
                model_revision=identity.model_revision,
                configuration_hash=configuration_hash,
            )
            if existing is not None:
                return existing.id

            model_id = uuid.uuid4()
            await uow.models.add_model(
                model_id=model_id,
                identity=identity,
                configuration_hash=configuration_hash,
            )
            await uow.commit()
            return model_id

    async def find_model(self, *, model_id: uuid.UUID) -> EmbeddingModelState | None:
        async with self._uow_factory() as uow:
            return await uow.models.find_model(model_id=model_id)


__all__ = ["EmbeddingModelRegistryService"]
