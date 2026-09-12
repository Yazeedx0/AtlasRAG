from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from atlasrag.contracts.error.embedding_errors import (
    EmbeddingInputTooLarge,
    EmbeddingProviderPermanentError,
    EmbeddingProviderTransientError,
    InvalidEmbeddingResponse,
)
from atlasrag.contracts.types.embedding import (
    EmbeddingBatchRequest,
    EmbeddingBatchResult,
    EmbeddingUsage,
    EmbeddingVector,
)

_RATE_LIMIT_STATUS_CODE = 429
_SERVER_ERROR_STATUS_CODE = 500
_REQUEST_TOO_LARGE_STATUS_CODE = 413
_RETRY_AFTER_HEADER = "retry-after"
_INPUT_TOO_LONG_MARKERS = ("maximum context length", "too many tokens", "reduce the length")

MISSING_EMBEDDING_DATA = "response contained no embedding data"
MISSING_EMBEDDING_INDEX = "response item did not carry an index"


class OpenAIEmbeddingProvider:
    def __init__(self, *, client: AsyncOpenAI) -> None:
        self._client = client

    async def embed(self, *, request: EmbeddingBatchRequest) -> EmbeddingBatchResult:
        try:
            response = await self._client.embeddings.create(
                model=request.model_name,
                input=[item.text for item in request.inputs],
            )
        except (APITimeoutError, APIConnectionError) as error:
            raise EmbeddingProviderTransientError(reason=type(error).__name__) from error
        except RateLimitError as error:
            raise EmbeddingProviderTransientError(
                reason=f"http_{error.status_code}",
                retry_after_seconds=_retry_after_seconds(error),
            ) from error
        except APIStatusError as error:
            raise _translate_status_error(error) from error

        if not response.data:
            raise InvalidEmbeddingResponse(reason=MISSING_EMBEDDING_DATA)

        vectors: list[EmbeddingVector] = []
        for item in response.data:
            if item.index is None:
                raise InvalidEmbeddingResponse(reason=MISSING_EMBEDDING_INDEX)
            vectors.append(
                EmbeddingVector(index=item.index, values=tuple(item.embedding))
            )

        return EmbeddingBatchResult(
            vectors=tuple(vectors),
            model=response.model,
            usage=EmbeddingUsage(
                input_tokens=response.usage.prompt_tokens,
                total_tokens=response.usage.total_tokens,
            ),
        )


def _retry_after_seconds(error: APIStatusError) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get(_RETRY_AFTER_HEADER)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _translate_status_error(
    error: APIStatusError,
) -> EmbeddingProviderTransientError | EmbeddingProviderPermanentError | EmbeddingInputTooLarge:
    reason = f"http_{error.status_code}"
    if error.status_code >= _SERVER_ERROR_STATUS_CODE:
        return EmbeddingProviderTransientError(reason=reason)
    if error.status_code == _RATE_LIMIT_STATUS_CODE:
        return EmbeddingProviderTransientError(
            reason=reason,
            retry_after_seconds=_retry_after_seconds(error),
        )
    if error.status_code == _REQUEST_TOO_LARGE_STATUS_CODE or _mentions_input_length(error):
        return EmbeddingInputTooLarge(reason=reason)
    return EmbeddingProviderPermanentError(reason=reason)


def _mentions_input_length(error: APIStatusError) -> bool:
    message = str(getattr(error, "message", "")).lower()
    return any(marker in message for marker in _INPUT_TOO_LONG_MARKERS)


__all__ = ["OpenAIEmbeddingProvider"]
