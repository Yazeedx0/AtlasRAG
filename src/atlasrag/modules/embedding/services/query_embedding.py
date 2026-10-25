from atlasrag.contracts.embedding import EmbeddingProvider
from atlasrag.contracts.error.embedding_errors import (
    EmbeddingInputInvalid,
    EmbeddingInputTooLarge,
    EmbeddingModelNotRegistered,
)
from atlasrag.contracts.types.ai_types import EmbeddingInputType
from atlasrag.contracts.types.embedding import (
    EmbeddingBatchRequest,
    EmbeddingInput,
    EmbeddingModelIdentity,
    QueryVector,
)
from atlasrag.modules.embedding.batching import exceeds_model_input_limit, ordered_vectors
from atlasrag.modules.embedding.services.model_registry import EmbeddingModelRegistryService

EMPTY_QUERY = "query is empty"
QUERY_EXCEEDS_MODEL_LIMIT = "query cannot fit the model input limit"


class QueryEmbeddingService:
    def __init__(
        self,
        *,
        registry: EmbeddingModelRegistryService,
        provider: EmbeddingProvider,
        identity: EmbeddingModelIdentity,
        max_chars_per_token: int,
    ) -> None:
        self._registry = registry
        self._provider = provider
        self._identity = identity
        self._max_chars_per_token = max_chars_per_token

    async def embed_query(self, *, query: str) -> QueryVector:
        text = query.strip()
        if not text:
            raise EmbeddingInputInvalid(reason=EMPTY_QUERY)

        model = await self._registry.find_by_identity(identity=self._identity)
        if model is None:
            raise EmbeddingModelNotRegistered(
                provider=self._identity.provider.value,
                model_name=self._identity.model_name,
                model_revision=self._identity.model_revision,
            )

        if exceeds_model_input_limit(
            text=text,
            model=model,
            max_chars_per_token=self._max_chars_per_token,
        ):
            raise EmbeddingInputTooLarge(reason=QUERY_EXCEEDS_MODEL_LIMIT)

        inputs = (EmbeddingInput(index=0, text=text),)
        result = await self._provider.embed(
            request=EmbeddingBatchRequest(
                model_name=model.model_name,
                inputs=inputs,
                input_type=EmbeddingInputType.QUERY,
            )
        )
        (values,) = ordered_vectors(result=result, inputs=inputs, dimension=model.dimension)
        return QueryVector(
            embedding_model_id=model.id,
            dimension=model.dimension,
            distance_metric=model.distance_metric,
            values=values,
        )


__all__ = ["EMPTY_QUERY", "QUERY_EXCEEDS_MODEL_LIMIT", "QueryEmbeddingService"]
