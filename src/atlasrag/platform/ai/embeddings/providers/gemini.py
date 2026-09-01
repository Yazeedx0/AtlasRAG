from typing import cast

from google.genai import Client
from google.genai.types import ContentListUnion, EmbedContentConfig

from atlasrag.contracts.error.ai_errors import AiError
from atlasrag.contracts.types.ai_types import EmbeddingInputType

_TASK_TYPES: dict[EmbeddingInputType, str] = {
    EmbeddingInputType.DOCUMENT: "RETRIEVAL_DOCUMENT",
    EmbeddingInputType.QUERY: "RETRIEVAL_QUERY",
}


class GeminiEmbedder:
    def __init__(self, *, client: Client, model: str) -> None:
        self._client = client
        self._model = model

    async def embed(
        self,
        *,
        texts: list[str],
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> list[list[float]]:
        response = await self._client.aio.models.embed_content(
            model=self._model,
            contents=cast(ContentListUnion, list(texts)),
            config=EmbedContentConfig(task_type=_TASK_TYPES[input_type]),
        )
        if response.embeddings is None:
            raise AiError("gemini returned no embeddings")
        vectors: list[list[float]] = []
        for embedding in response.embeddings:
            if embedding.values is None:
                raise AiError("gemini returned an embedding without values")
            vectors.append(list(embedding.values))
        return vectors


__all__ = ["GeminiEmbedder"]
