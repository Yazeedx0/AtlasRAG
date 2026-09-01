from google.genai import Client
from google.genai.types import GenerateContentConfig

from atlasrag.contracts.types.ai_types import GeneratedText


class GeminiTextGenerator:
    def __init__(self, *, client: Client, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int,
    ) -> GeneratedText:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_output_tokens,
            ),
        )
        return GeneratedText(text=response.text or "", model=self._model)


__all__ = ["GeminiTextGenerator"]
