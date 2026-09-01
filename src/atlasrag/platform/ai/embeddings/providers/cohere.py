from cohere import AsyncClientV2

from atlasrag.contracts.error.ai_errors import AiError
from atlasrag.contracts.types.ai_types import EmbeddingInputType

_INPUT_TYPES: dict[EmbeddingInputType, str] = {
    EmbeddingInputType.DOCUMENT: "search_document",
    EmbeddingInputType.QUERY: "search_query",
}


class CohereEmbedder:
    def __init__(self, *, client: AsyncClientV2, model: str) -> None:
        self._client = client
        self._model = model

    async def embed(
        self,
        *,
        texts: list[str],
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> list[list[float]]:
        response = await self._client.embed(
            model=self._model,
            texts=texts,
            input_type=_INPUT_TYPES[input_type],
            embedding_types=["float"],
        )
        embeddings = response.embeddings.float_
        if embeddings is None:
            raise AiError("cohere returned no float embeddings")
        return [list(vector) for vector in embeddings]


__all__ = ["CohereEmbedder"]
