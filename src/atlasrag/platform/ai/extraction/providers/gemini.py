import httpx
from google.genai import Client
from google.genai.errors import APIError, ClientError, ServerError
from google.genai.types import GenerateContentConfig, Part

from atlasrag.contracts.error.extraction_errors import (
    ExtractionProviderPermanentError,
    ExtractionProviderTransientError,
)
from atlasrag.contracts.types.extraction import ExtractedDocument, ExtractionMethod
from atlasrag.contracts.types.ingestion import LoadedArtifact

from ._normalization import EXTRACTION_INSTRUCTIONS, normalize_extraction_payload

_RETRYABLE_STATUS_CODE = 429
_TRANSCRIBE_PROMPT = "Transcribe this document."


class VlmDocumentExtractor:
    def __init__(
        self,
        *,
        client: Client,
        model: str,
        max_output_tokens: int,
    ) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def extract(self, *, artifact: LoadedArtifact) -> ExtractedDocument:
        document_part = Part.from_bytes(
            data=artifact.content,
            mime_type=artifact.mime_type,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[document_part, _TRANSCRIBE_PROMPT],
                config=GenerateContentConfig(
                    system_instruction=EXTRACTION_INSTRUCTIONS,
                    max_output_tokens=self._max_output_tokens,
                    response_mime_type="application/json",
                ),
            )
        except ServerError as error:
            raise ExtractionProviderTransientError(
                method=ExtractionMethod.VLM,
                reason=f"http_{error.code}",
            ) from error
        except ClientError as error:
            raise self._translate_client_error(error) from error
        except APIError as error:
            raise ExtractionProviderTransientError(
                method=ExtractionMethod.VLM,
                reason=f"http_{error.code}",
            ) from error
        except httpx.RequestError as error:
            raise ExtractionProviderTransientError(
                method=ExtractionMethod.VLM,
                reason=type(error).__name__,
            ) from error

        return normalize_extraction_payload(
            response_text=response.text or "",
            method=ExtractionMethod.VLM,
            metadata={"model": self._model},
        )

    @staticmethod
    def _translate_client_error(
        error: ClientError,
    ) -> ExtractionProviderTransientError | ExtractionProviderPermanentError:
        reason = f"http_{error.code}"
        if error.code == _RETRYABLE_STATUS_CODE:
            return ExtractionProviderTransientError(
                method=ExtractionMethod.VLM,
                reason=reason,
            )
        return ExtractionProviderPermanentError(
            method=ExtractionMethod.VLM,
            reason=reason,
        )


__all__ = ["VlmDocumentExtractor"]
