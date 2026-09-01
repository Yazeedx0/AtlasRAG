from openai import AsyncOpenAI, omit

from atlasrag.contracts.types.ai_types import GeneratedText


class OpenAITextGenerator:
    def __init__(self, *, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int,
    ) -> GeneratedText:
        response = await self._client.responses.create(
            model=self._model,
            input=prompt,
            instructions=omit if system is None else system,
            max_output_tokens=max_output_tokens,
        )
        return GeneratedText(text=response.output_text, model=self._model)


__all__ = ["OpenAITextGenerator"]
