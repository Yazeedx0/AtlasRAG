import base64

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from atlasrag.contracts.error.extraction_errors import (
    ExtractionProviderPermanentError,
    ExtractionProviderTransientError,
)
from atlasrag.contracts.types.extraction import ExtractedDocument, ExtractionMethod
from atlasrag.contracts.types.ingestion import LoadedArtifact

from ._normalization import EXTRACTION_INSTRUCTIONS, normalize_extraction_payload

_IMAGE_MIME_PREFIX = "image/"
_RETRYABLE_STATUS_CODE = 429
_SERVER_ERROR_STATUS_CODE = 500


class OpenAIOcrExtractor:
    def __init__(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        max_output_tokens: int,
    ) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def extract(self, *, artifact: LoadedArtifact) -> ExtractedDocument:
        content = self._build_input_content(artifact=artifact)
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=EXTRACTION_INSTRUCTIONS,
                input=[{"role": "user", "content": content}],
                max_output_tokens=self._max_output_tokens,
            )
        except (APITimeoutError, APIConnectionError, RateLimitError) as error:
            raise ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason=type(error).__name__,
            ) from error
        except APIStatusError as error:
            raise self._translate_status_error(error) from error

        return normalize_extraction_payload(
            response_text=response.output_text,
            method=ExtractionMethod.OPENAI_OCR,
            metadata={"model": self._model},
        )

    def _build_input_content(self, *, artifact: LoadedArtifact) -> list[dict[str, str]]:
        encoded = base64.b64encode(artifact.content).decode("ascii")
        data_url = f"data:{artifact.mime_type};base64,{encoded}"
        if artifact.mime_type.startswith(_IMAGE_MIME_PREFIX):
            source = {"type": "input_image", "image_url": data_url, "detail": "high"}
        else:
            source = {
                "type": "input_file",
                "filename": f"{artifact.artifact_id}",
                "file_data": data_url,
            }
        return [source, {"type": "input_text", "text": "Transcribe this document."}]

    @staticmethod
    def _translate_status_error(
        error: APIStatusError,
    ) -> ExtractionProviderTransientError | ExtractionProviderPermanentError:
        reason = f"http_{error.status_code}"
        if (
            error.status_code >= _SERVER_ERROR_STATUS_CODE
            or error.status_code == _RETRYABLE_STATUS_CODE
        ):
            return ExtractionProviderTransientError(
                method=ExtractionMethod.OPENAI_OCR,
                reason=reason,
            )
        return ExtractionProviderPermanentError(
            method=ExtractionMethod.OPENAI_OCR,
            reason=reason,
        )


__all__ = ["OpenAIOcrExtractor"]
