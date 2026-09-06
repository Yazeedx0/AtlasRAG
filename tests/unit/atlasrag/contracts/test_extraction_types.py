import dataclasses

import pytest

from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
    ExtractionMethod,
    ExtractionResult,
)


def make_block() -> ExtractedBlock:
    return ExtractedBlock(text="text", block_type=ExtractedBlockType.PARAGRAPH)


def test_extracted_block_is_immutable() -> None:
    block = make_block()

    with pytest.raises(dataclasses.FrozenInstanceError):
        block.text = "changed"


def test_block_metadata_default_cannot_be_mutated() -> None:
    block = make_block()

    with pytest.raises(TypeError):
        block.metadata["injected"] = True


def test_block_metadata_default_is_not_shared_state() -> None:
    first = make_block()

    with pytest.raises(TypeError):
        first.metadata["injected"] = True

    assert dict(make_block().metadata) == {}


def test_document_metadata_default_cannot_be_mutated() -> None:
    document = ExtractedDocument(blocks=(make_block(),))

    with pytest.raises(TypeError):
        document.metadata["injected"] = True


def test_extraction_result_records_the_method_actually_used() -> None:
    result = ExtractionResult(
        document=ExtractedDocument(blocks=(make_block(),)),
        method=ExtractionMethod.VLM,
        fallback_used=True,
        fallback_reason="ocr_timeout",
        quality_score=0.8,
    )

    assert result.method is ExtractionMethod.VLM
    assert result.method.value == "vlm"
    assert result.fallback_used is True
    assert result.fallback_reason == "ocr_timeout"
