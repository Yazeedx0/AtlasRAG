from anthropic import AsyncAnthropic, omit

from atlasrag.contracts.types.ai_types import GeneratedText


class AnthropicTextGenerator:
    def __init__(self, *, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    async def generate(
        self,
        *,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int,
    ) -> GeneratedText:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
            system=omit if system is None else system,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return GeneratedText(text=text, model=self._model)


__all__ = ["AnthropicTextGenerator"]
