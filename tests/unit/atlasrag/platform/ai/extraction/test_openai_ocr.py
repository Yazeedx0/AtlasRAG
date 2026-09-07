import base64
import hashlib
import json
from typing import Any, cast
from uuid import uuid4

import httpx2 as httpx
import pytest
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
from atlasrag.contracts.types.extraction import ExtractedBlockType, ExtractedDocument
from atlasrag.contracts.types.ingestion import LoadedArtifact
from atlasrag.platform.ai.extraction.providers.openai import OpenAIOcrExtractor

MODEL = "gpt-4o"
PDF_CONTENT = b"%PDF-1.7 fake document bytes"


def make_artifact(
    *,
    content: bytes = PDF_CONTENT,
    mime_type: str = "application/pdf",
) -> LoadedArtifact:
    digest = hashlib.sha256(content).hexdigest()
    return LoadedArtifact(
        artifact_id=uuid4(),
        content=content,
        mime_type=mime_type,
        expected_file_hash=digest,
        observed_file_hash=digest,
        file_size_bytes=len(content),
    )


class FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class FakeResponses:
    def __init__(self, *, output_text: str = "", error: Exception | None = None) -> None:
        self._output_text = output_text
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return FakeResponse(self._output_text)


class FakeClient:
    def __init__(self, *, output_text: str = "", error: Exception | None = None) -> None:
        self.responses = FakeResponses(output_text=output_text, error=error)


def make_extractor(client: FakeClient) -> OpenAIOcrExtractor:
    return OpenAIOcrExtractor(
        client=cast(AsyncOpenAI, client),
        model=MODEL,
        max_output_tokens=16000,
    )


def ocr_payload(*blocks: dict[str, Any]) -> str:
    return json.dumps({"blocks": list(blocks)})


def status_error(status_code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code, request=request)
    return APIStatusError("boom", response=response, body=None)


@pytest.mark.asyncio
async def test_provider_response_is_normalized_into_extracted_blocks() -> None:
    client = FakeClient(
        output_text=ocr_payload(
            {"text": "Annual Leave", "block_type": "heading", "page_number": 4},
            {"text": "Employees are entitled to...", "block_type": "paragraph", "page_number": 4},
            {"text": "| Grade | Days |", "block_type": "table", "page_number": 5},
        )
    )

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert isinstance(document, ExtractedDocument)
    assert len(document.blocks) == 3
    assert document.blocks[0].text == "Annual Leave"
    assert document.blocks[0].block_type is ExtractedBlockType.HEADING
    assert document.blocks[0].page_number == 4
    assert document.blocks[1].block_type is ExtractedBlockType.PARAGRAPH
    assert document.blocks[2].block_type is ExtractedBlockType.TABLE
    assert document.blocks[2].page_number == 5


@pytest.mark.asyncio
async def test_document_metadata_records_the_model_without_leaking_provider_types() -> None:
    client = FakeClient(output_text=ocr_payload({"text": "body", "block_type": "paragraph"}))

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert dict(document.metadata) == {"model": MODEL}


@pytest.mark.asyncio
async def test_pdf_artifact_is_sent_as_an_inline_base64_file() -> None:
    client = FakeClient(output_text=ocr_payload({"text": "body", "block_type": "paragraph"}))
    artifact = make_artifact()

    await make_extractor(client).extract(artifact=artifact)

    request = client.responses.calls[0]
    assert request["model"] == MODEL
    assert request["max_output_tokens"] == 16000
    source = request["input"][0]["content"][0]
    expected = base64.b64encode(artifact.content).decode("ascii")
    assert source["type"] == "input_file"
    assert source["file_data"] == f"data:application/pdf;base64,{expected}"


@pytest.mark.asyncio
async def test_image_artifact_is_sent_as_an_image_input() -> None:
    client = FakeClient(output_text=ocr_payload({"text": "body", "block_type": "paragraph"}))
    artifact = make_artifact(content=b"\x89PNG fake", mime_type="image/png")

    await make_extractor(client).extract(artifact=artifact)

    source = client.responses.calls[0]["input"][0]["content"][0]
    expected = base64.b64encode(artifact.content).decode("ascii")
    assert source["type"] == "input_image"
    assert source["image_url"] == f"data:image/png;base64,{expected}"


@pytest.mark.asyncio
async def test_unknown_block_type_falls_back_to_other() -> None:
    client = FakeClient(output_text=ocr_payload({"text": "body", "block_type": "footnote"}))

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert document.blocks[0].block_type is ExtractedBlockType.OTHER


@pytest.mark.asyncio
async def test_missing_block_type_falls_back_to_other() -> None:
    client = FakeClient(output_text=ocr_payload({"text": "body"}))

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert document.blocks[0].block_type is ExtractedBlockType.OTHER


@pytest.mark.asyncio
@pytest.mark.parametrize("page_number", [0, -1, "4", True, None])
async def test_invalid_page_numbers_are_discarded(page_number: object) -> None:
    client = FakeClient(
        output_text=ocr_payload(
            {"text": "body", "block_type": "paragraph", "page_number": page_number}
        )
    )

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert document.blocks[0].page_number is None


@pytest.mark.asyncio
async def test_blank_and_malformed_blocks_are_dropped() -> None:
    client = FakeClient(
        output_text=ocr_payload(
            {"text": "kept", "block_type": "paragraph"},
            {"text": "   ", "block_type": "paragraph"},
            {"block_type": "paragraph"},
            {"text": 42, "block_type": "paragraph"},
        )
    )

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert len(document.blocks) == 1
    assert document.blocks[0].text == "kept"


@pytest.mark.asyncio
async def test_empty_provider_output_yields_an_empty_document() -> None:
    client = FakeClient(output_text=ocr_payload())

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert document.blocks == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output_text",
    ["not json at all", '["blocks"]', '{"pages": []}', '{"blocks": "text"}'],
)
async def test_unusable_provider_payloads_fail_permanently(output_text: str) -> None:
    client = FakeClient(output_text=output_text)

    with pytest.raises(ExtractionProviderPermanentError):
        await make_extractor(client).extract(artifact=make_artifact())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses")),
        APIConnectionError(
            request=httpx.Request("POST", "https://api.openai.com/v1/responses")
        ),
        status_error(500),
        status_error(503),
        status_error(429),
    ],
)
async def test_retryable_provider_failures_are_transient(error: Exception) -> None:
    client = FakeClient(error=error)

    with pytest.raises(ExtractionProviderTransientError):
        await make_extractor(client).extract(artifact=make_artifact())


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
async def test_client_side_provider_failures_are_permanent(status_code: int) -> None:
    client = FakeClient(error=status_error(status_code))

    with pytest.raises(ExtractionProviderPermanentError) as error:
        await make_extractor(client).extract(artifact=make_artifact())

    assert error.value.reason == f"http_{status_code}"


@pytest.mark.asyncio
async def test_rate_limit_error_is_transient() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429, request=request)
    client = FakeClient(error=RateLimitError("slow down", response=response, body=None))

    with pytest.raises(ExtractionProviderTransientError):
        await make_extractor(client).extract(artifact=make_artifact())
