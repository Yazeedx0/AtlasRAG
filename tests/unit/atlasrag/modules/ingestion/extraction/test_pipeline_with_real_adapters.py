import hashlib
import json
from typing import Any, cast
from uuid import uuid4

import httpx
import httpx2
import pytest
from google.genai import Client
from google.genai.errors import ServerError
from openai import APIStatusError, AsyncOpenAI

from atlasrag.contracts.error.extraction_errors import ExtractionFailed
from atlasrag.contracts.types.extraction import ExtractedBlockType, ExtractionMethod
from atlasrag.contracts.types.ingestion import LoadedArtifact
from atlasrag.modules.ingestion.extraction.pipeline import ExtractionPipeline
from atlasrag.modules.ingestion.extraction.quality import ShadowExtractionQualityGate
from atlasrag.platform.ai.extraction.providers.gemini import VlmDocumentExtractor
from atlasrag.platform.ai.extraction.providers.openai import OpenAIOcrExtractor

OCR_MODEL = "gpt-4o"
VLM_MODEL = "gemini-2.0-flash"


def payload(text: str) -> str:
    return json.dumps({"blocks": [{"text": text, "block_type": "heading", "page_number": 1}]})


def make_artifact() -> LoadedArtifact:
    content = b"%PDF-1.7 document"
    digest = hashlib.sha256(content).hexdigest()
    return LoadedArtifact(
        artifact_id=uuid4(),
        content=content,
        mime_type="application/pdf",
        expected_file_hash=digest,
        observed_file_hash=digest,
        file_size_bytes=len(content),
    )


class FakeOpenAiResponses:
    def __init__(self, *, output_text: str = "", error: Exception | None = None) -> None:
        self._output_text = output_text
        self._error = error
        self.call_count = 0

    async def create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return type("R", (), {"output_text": self._output_text})()


class FakeOpenAiClient:
    def __init__(self, *, output_text: str = "", error: Exception | None = None) -> None:
        self.responses = FakeOpenAiResponses(output_text=output_text, error=error)


class FakeGeminiModels:
    def __init__(self, *, text: str = "", error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.call_count = 0

    async def generate_content(self, **kwargs: Any) -> Any:
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return type("R", (), {"text": self._text})()


class FakeGeminiClient:
    def __init__(self, *, text: str = "", error: Exception | None = None) -> None:
        self.models = FakeGeminiModels(text=text, error=error)
        self.aio = type("Aio", (), {"models": self.models})()


def openai_status_error(status_code: int) -> APIStatusError:
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    return APIStatusError(
        "boom",
        response=httpx2.Response(status_code, request=request),
        body=None,
    )


def gemini_server_error(code: int) -> ServerError:
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com")
    return ServerError(code, {"error": {"message": "boom"}}, httpx.Response(code, request=request))


def build_pipeline(
    *,
    openai_client: FakeOpenAiClient,
    gemini_client: FakeGeminiClient,
) -> ExtractionPipeline:
    return ExtractionPipeline(
        primary=OpenAIOcrExtractor(
            client=cast(AsyncOpenAI, openai_client),
            model=OCR_MODEL,
            max_output_tokens=16000,
        ),
        fallback=VlmDocumentExtractor(
            client=cast(Client, gemini_client),
            model=VLM_MODEL,
            max_output_tokens=16000,
        ),
        quality_gate=ShadowExtractionQualityGate(),
    )


@pytest.mark.asyncio
async def test_ocr_success_returns_ocr_result_without_calling_the_vlm() -> None:
    openai_client = FakeOpenAiClient(output_text=payload("From OCR"))
    gemini_client = FakeGeminiClient(text=payload("From VLM"))
    pipeline = build_pipeline(openai_client=openai_client, gemini_client=gemini_client)

    result = await pipeline.extract(artifact=make_artifact(), language_code="ar")

    assert gemini_client.models.call_count == 0
    assert result.method is ExtractionMethod.OPENAI_OCR
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.quality_score == 1.0
    assert result.document.blocks[0].text == "From OCR"
    assert result.document.blocks[0].block_type is ExtractedBlockType.HEADING


@pytest.mark.asyncio
async def test_ocr_technical_failure_routes_to_the_vlm_and_records_the_method() -> None:
    openai_client = FakeOpenAiClient(error=openai_status_error(503))
    gemini_client = FakeGeminiClient(text=payload("From VLM"))
    pipeline = build_pipeline(openai_client=openai_client, gemini_client=gemini_client)

    result = await pipeline.extract(artifact=make_artifact())

    assert gemini_client.models.call_count == 1
    assert result.method is ExtractionMethod.VLM
    assert result.fallback_used is True
    assert result.fallback_reason == "http_503"
    assert result.document.blocks[0].text == "From VLM"


@pytest.mark.asyncio
async def test_malformed_ocr_output_routes_to_the_vlm() -> None:
    openai_client = FakeOpenAiClient(output_text="not json")
    gemini_client = FakeGeminiClient(text=payload("From VLM"))
    pipeline = build_pipeline(openai_client=openai_client, gemini_client=gemini_client)

    result = await pipeline.extract(artifact=make_artifact())

    assert result.method is ExtractionMethod.VLM
    assert result.fallback_reason == "malformed_provider_response"


@pytest.mark.asyncio
async def test_both_providers_failing_transiently_is_retryable() -> None:
    pipeline = build_pipeline(
        openai_client=FakeOpenAiClient(error=openai_status_error(500)),
        gemini_client=FakeGeminiClient(error=gemini_server_error(503)),
    )

    with pytest.raises(ExtractionFailed) as error:
        await pipeline.extract(artifact=make_artifact())

    assert error.value.retryable is True
    assert error.value.primary_reason == "http_500"
    assert error.value.fallback_reason == "http_503"


@pytest.mark.asyncio
async def test_permanent_vlm_failure_after_ocr_failure_is_not_retryable() -> None:
    pipeline = build_pipeline(
        openai_client=FakeOpenAiClient(error=openai_status_error(500)),
        gemini_client=FakeGeminiClient(text="not json either"),
    )

    with pytest.raises(ExtractionFailed) as error:
        await pipeline.extract(artifact=make_artifact())

    assert error.value.retryable is False
    assert error.value.fallback_reason == "malformed_provider_response"
