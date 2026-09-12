from typing import Any

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from atlasrag.contracts.error.embedding_errors import (
    EmbeddingInputTooLarge,
    EmbeddingProviderPermanentError,
    EmbeddingProviderTransientError,
    InvalidEmbeddingResponse,
)
from atlasrag.contracts.types.embedding import EmbeddingBatchRequest, EmbeddingInput
from atlasrag.platform.ai.embeddings.providers import OpenAIEmbeddingProvider

pytestmark = pytest.mark.unit

REQUEST = EmbeddingBatchRequest(
    model_name="text-embedding-3-small",
    inputs=(EmbeddingInput(index=0, text="alpha"), EmbeddingInput(index=1, text="beta")),
)


class FakeEmbeddingItem:
    def __init__(self, index: int | None, embedding: list[float]) -> None:
        self.index = index
        self.embedding = embedding


class FakeUsage:
    def __init__(self, prompt_tokens: int, total_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.total_tokens = total_tokens


class FakeResponse:
    def __init__(self, data: list[FakeEmbeddingItem]) -> None:
        self.data = data
        self.model = "text-embedding-3-small"
        self.usage = FakeUsage(prompt_tokens=7, total_tokens=7)


class FakeEmbeddings:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class FakeClient:
    def __init__(self, embeddings: FakeEmbeddings) -> None:
        self.embeddings = embeddings


def make_provider(
    *,
    response: object = None,
    error: Exception | None = None,
) -> tuple[OpenAIEmbeddingProvider, FakeEmbeddings]:
    embeddings = FakeEmbeddings(response=response, error=error)
    return OpenAIEmbeddingProvider(client=FakeClient(embeddings)), embeddings  # type: ignore[arg-type]


def http_response(status_code: int, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers=headers or {},
        request=httpx.Request("POST", "https://api.openai.com/v1/embeddings"),
    )


@pytest.mark.asyncio
async def test_provider_returns_indexed_vectors_and_usage() -> None:
    provider, embeddings = make_provider(
        response=FakeResponse(
            [
                FakeEmbeddingItem(1, [0.4, 0.5]),
                FakeEmbeddingItem(0, [0.1, 0.2]),
            ]
        )
    )

    result = await provider.embed(request=REQUEST)

    assert embeddings.calls == [
        {"model": "text-embedding-3-small", "input": ["alpha", "beta"]}
    ]
    assert {vector.index: vector.values for vector in result.vectors} == {
        0: (0.1, 0.2),
        1: (0.4, 0.5),
    }
    assert result.usage.input_tokens == 7
    assert result.usage.total_tokens == 7


@pytest.mark.asyncio
async def test_empty_response_data_is_an_invalid_response() -> None:
    provider, _ = make_provider(response=FakeResponse([]))

    with pytest.raises(InvalidEmbeddingResponse):
        await provider.embed(request=REQUEST)


@pytest.mark.asyncio
async def test_missing_index_is_an_invalid_response() -> None:
    provider, _ = make_provider(response=FakeResponse([FakeEmbeddingItem(None, [0.1])]))

    with pytest.raises(InvalidEmbeddingResponse):
        await provider.embed(request=REQUEST)


@pytest.mark.asyncio
async def test_timeout_is_transient() -> None:
    provider, _ = make_provider(
        error=APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
    )

    with pytest.raises(EmbeddingProviderTransientError):
        await provider.embed(request=REQUEST)


@pytest.mark.asyncio
async def test_connection_error_is_transient() -> None:
    provider, _ = make_provider(
        error=APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    )

    with pytest.raises(EmbeddingProviderTransientError):
        await provider.embed(request=REQUEST)


@pytest.mark.asyncio
async def test_rate_limit_is_transient_and_carries_retry_after() -> None:
    provider, _ = make_provider(
        error=RateLimitError(
            "slow down",
            response=http_response(429, headers={"retry-after": "12"}),
            body=None,
        )
    )

    with pytest.raises(EmbeddingProviderTransientError) as error:
        await provider.embed(request=REQUEST)

    assert error.value.retry_after_seconds == 12.0


@pytest.mark.asyncio
async def test_server_error_is_transient() -> None:
    provider, _ = make_provider(
        error=InternalServerError("boom", response=http_response(500), body=None)
    )

    with pytest.raises(EmbeddingProviderTransientError):
        await provider.embed(request=REQUEST)


@pytest.mark.asyncio
async def test_authentication_error_is_permanent() -> None:
    provider, _ = make_provider(
        error=AuthenticationError("bad key", response=http_response(401), body=None)
    )

    with pytest.raises(EmbeddingProviderPermanentError):
        await provider.embed(request=REQUEST)


@pytest.mark.asyncio
async def test_context_length_rejection_is_reported_as_input_too_large() -> None:
    provider, _ = make_provider(
        error=BadRequestError(
            "This model's maximum context length is 8192 tokens",
            response=http_response(400),
            body=None,
        )
    )

    with pytest.raises(EmbeddingInputTooLarge):
        await provider.embed(request=REQUEST)


@pytest.mark.asyncio
async def test_payload_too_large_is_reported_as_input_too_large() -> None:
    provider, _ = make_provider(
        error=APIStatusError("too big", response=http_response(413), body=None)
    )

    with pytest.raises(EmbeddingInputTooLarge):
        await provider.embed(request=REQUEST)
