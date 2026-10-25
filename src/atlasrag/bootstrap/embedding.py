from atlasrag.bootstrap.core.config import Settings
from atlasrag.contracts.types.embedding import EmbeddingModelIdentity


def embedding_model_identity(settings: Settings) -> EmbeddingModelIdentity:
    return EmbeddingModelIdentity(
        provider=settings.EMBEDDING_PROVIDER,
        model_name=settings.EMBEDDING_MODEL,
        model_revision=settings.EMBEDDING_MODEL_REVISION,
        dimension=settings.EMBEDDING_DIMENSION,
        distance_metric=settings.EMBEDDING_DISTANCE_METRIC,
        max_input_tokens=settings.EMBEDDING_MAX_INPUT_TOKENS,
    )


__all__ = ["embedding_model_identity"]
