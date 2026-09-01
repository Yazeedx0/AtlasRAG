from cohere import AsyncClientV2

from atlasrag.contracts.types.ai_types import RankedDocument


class CohereReranker:
    def __init__(self, *, client: AsyncClientV2, model: str) -> None:
        self._client = client
        self._model = model

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[RankedDocument]:
        response = await self._client.rerank(
            model=self._model,
            query=query,
            documents=documents,
            top_n=top_n,
        )
        return [
            RankedDocument(index=result.index, relevance_score=result.relevance_score)
            for result in response.results
        ]


__all__ = ["CohereReranker"]
