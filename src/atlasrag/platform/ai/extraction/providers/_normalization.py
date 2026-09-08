import json
from typing import Any

from atlasrag.contracts.error.extraction_errors import ExtractionProviderPermanentError
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
    ExtractionMethod,
)

EXTRACTION_INSTRUCTIONS = (
    "You are a document transcription engine. Transcribe the document exactly as it "
    "appears, preserving reading order. Respond with a single JSON object of the form "
    '{"blocks": [{"text": str, "block_type": str, "page_number": int}]}. '
    "block_type must be one of: heading, paragraph, table, list, code, other. "
    "Render tables as markdown inside the text field. Do not translate, summarize, "
    "or add commentary. Return only the JSON object."
)

MALFORMED_PROVIDER_RESPONSE = "malformed_provider_response"
MISSING_BLOCKS = "missing_blocks"
_BLOCKS_KEY = "blocks"
_JSON_FENCE = "```"


def normalize_extraction_payload(
    *,
    response_text: str,
    method: ExtractionMethod,
    metadata: dict[str, object],
) -> ExtractedDocument:
    payload = _parse_payload(response_text=response_text, method=method)
    raw_blocks = payload.get(_BLOCKS_KEY)
    if not isinstance(raw_blocks, list):
        raise ExtractionProviderPermanentError(method=method, reason=MISSING_BLOCKS)

    blocks = tuple(
        block
        for raw_block in raw_blocks
        if (block := _normalize_block(raw_block)) is not None
    )
    return ExtractedDocument(blocks=blocks, metadata=metadata)


def _parse_payload(*, response_text: str, method: ExtractionMethod) -> dict[str, Any]:
    try:
        payload = json.loads(_strip_code_fence(response_text))
    except json.JSONDecodeError as error:
        raise ExtractionProviderPermanentError(
            method=method,
            reason=MALFORMED_PROVIDER_RESPONSE,
        ) from error

    if not isinstance(payload, dict):
        raise ExtractionProviderPermanentError(
            method=method,
            reason=MALFORMED_PROVIDER_RESPONSE,
        )
    return payload


def _strip_code_fence(response_text: str) -> str:
    text = response_text.strip()
    if not text.startswith(_JSON_FENCE):
        return text

    without_open = text[len(_JSON_FENCE) :].removeprefix("json").lstrip()
    return without_open.removesuffix(_JSON_FENCE).rstrip()


def _normalize_block(raw_block: object) -> ExtractedBlock | None:
    if not isinstance(raw_block, dict):
        return None

    text = raw_block.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    raw_type = raw_block.get("block_type")
    block_type = ExtractedBlockType.OTHER
    if isinstance(raw_type, str):
        try:
            block_type = ExtractedBlockType(raw_type.strip().lower())
        except ValueError:
            block_type = ExtractedBlockType.OTHER

    raw_page = raw_block.get("page_number")
    page_number = (
        raw_page
        if isinstance(raw_page, int) and not isinstance(raw_page, bool) and raw_page > 0
        else None
    )

    return ExtractedBlock(text=text, block_type=block_type, page_number=page_number)


__all__ = [
    "EXTRACTION_INSTRUCTIONS",
    "MALFORMED_PROVIDER_RESPONSE",
    "MISSING_BLOCKS",
    "normalize_extraction_payload",
]
