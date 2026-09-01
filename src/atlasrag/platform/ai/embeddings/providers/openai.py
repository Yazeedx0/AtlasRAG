from openai import AsyncOpenAI

from atlasrag.contracts.types.ai_types import EmbeddingInputType


class OpenAIEmbedder:
    def __init__(self, *, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def embed(
        self,
        *,
        texts: list[str],
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]


__all__ = ["OpenAIEmbedder"]
