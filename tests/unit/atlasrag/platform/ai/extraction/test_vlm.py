import hashlib
import json
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from google.genai import Client
from google.genai.errors import ClientError, ServerError

from atlasrag.contracts.error.extraction_errors import (
    ExtractionProviderPermanentError,
    ExtractionProviderTransientError,
)
from atlasrag.contracts.types.extraction import ExtractedBlockType, ExtractedDocument
from atlasrag.contracts.types.ingestion import LoadedArtifact
from atlasrag.platform.ai.extraction.providers.gemini import VlmDocumentExtractor

MODEL = "gemini-2.0-flash"
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
    def __init__(self, text: str | None) -> None:
        self.text = text


class FakeModels:
    def __init__(self, *, text: str | None = "", error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return FakeResponse(self._text)


class FakeAio:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


class FakeClient:
    def __init__(self, *, text: str | None = "", error: Exception | None = None) -> None:
        self.models = FakeModels(text=text, error=error)
        self.aio = FakeAio(self.models)


def make_extractor(client: FakeClient) -> VlmDocumentExtractor:
    return VlmDocumentExtractor(
        client=cast(Client, client),
        model=MODEL,
        max_output_tokens=16000,
    )


def vlm_payload(*blocks: dict[str, Any]) -> str:
    return json.dumps({"blocks": list(blocks)})


def api_error(error_type: type[ClientError] | type[ServerError], code: int) -> Exception:
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com")
    response = httpx.Response(code, request=request, json={"error": {"message": "boom"}})
    return error_type(code, {"error": {"message": "boom"}}, response)


@pytest.mark.asyncio
async def test_vlm_response_is_normalized_into_extracted_blocks() -> None:
    client = FakeClient(
        text=vlm_payload(
            {"text": "Annual Leave", "block_type": "heading", "page_number": 4},
            {"text": "Employees are entitled to...", "block_type": "paragraph"},
        )
    )

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert isinstance(document, ExtractedDocument)
    assert len(document.blocks) == 2
    assert document.blocks[0].block_type is ExtractedBlockType.HEADING
    assert document.blocks[0].page_number == 4
    assert document.blocks[1].block_type is ExtractedBlockType.PARAGRAPH


@pytest.mark.asyncio
async def test_vlm_returns_the_same_contract_type_as_the_ocr_extractor() -> None:
    client = FakeClient(text=vlm_payload({"text": "body", "block_type": "paragraph"}))

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert dict(document.metadata) == {"model": MODEL}
    assert all(isinstance(b.block_type, ExtractedBlockType) for b in document.blocks)


@pytest.mark.asyncio
async def test_artifact_bytes_are_sent_with_their_mime_type() -> None:
    client = FakeClient(text=vlm_payload({"text": "body", "block_type": "paragraph"}))
    artifact = make_artifact()

    await make_extractor(client).extract(artifact=artifact)

    request = client.models.calls[0]
    assert request["model"] == MODEL
    document_part = request["contents"][0]
    assert document_part.inline_data.data == artifact.content
    assert document_part.inline_data.mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_json_wrapped_in_a_code_fence_is_accepted() -> None:
    payload = vlm_payload({"text": "body", "block_type": "paragraph"})
    client = FakeClient(text=f"```json\n{payload}\n```")

    document = await make_extractor(client).extract(artifact=make_artifact())

    assert document.blocks[0].text == "body"


@pytest.mark.asyncio
async def test_empty_provider_text_fails_permanently() -> None:
    client = FakeClient(text=None)

    with pytest.raises(ExtractionProviderPermanentError) as error:
        await make_extractor(client).extract(artifact=make_artifact())

    assert error.value.reason == "malformed_provider_response"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [500, 502, 503])
async def test_server_errors_are_transient(code: int) -> None:
    client = FakeClient(error=api_error(ServerError, code))

    with pytest.raises(ExtractionProviderTransientError) as error:
        await make_extractor(client).extract(artifact=make_artifact())

    assert error.value.reason == f"http_{code}"


@pytest.mark.asyncio
async def test_rate_limit_client_error_is_transient() -> None:
    client = FakeClient(error=api_error(ClientError, 429))

    with pytest.raises(ExtractionProviderTransientError):
        await make_extractor(client).extract(artifact=make_artifact())


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 403, 404])
async def test_client_errors_are_permanent(code: int) -> None:
    client = FakeClient(error=api_error(ClientError, code))

    with pytest.raises(ExtractionProviderPermanentError) as error:
        await make_extractor(client).extract(artifact=make_artifact())

    assert error.value.reason == f"http_{code}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
    ],
)
async def test_network_failures_do_not_leak_and_are_transient(error: Exception) -> None:
    client = FakeClient(error=error)

    with pytest.raises(ExtractionProviderTransientError):
        await make_extractor(client).extract(artifact=make_artifact())
