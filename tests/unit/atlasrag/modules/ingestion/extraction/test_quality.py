from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)
from atlasrag.modules.ingestion.extraction.quality import (
    EMPTY_BLOCK_TEXT,
    EMPTY_DOCUMENT,
    ShadowExtractionQualityGate,
)


def make_document(*texts: str) -> ExtractedDocument:
    return ExtractedDocument(
        blocks=tuple(
            ExtractedBlock(text=text, block_type=ExtractedBlockType.PARAGRAPH)
            for text in texts
        )
    )


def test_document_with_only_populated_blocks_scores_one() -> None:
    assessment = ShadowExtractionQualityGate().evaluate(
        document=make_document("first", "second"),
        language_code="en",
    )

    assert assessment.score == 1.0
    assert assessment.reason_codes == ()


def test_empty_document_scores_zero_with_reason_code() -> None:
    assessment = ShadowExtractionQualityGate().evaluate(
        document=ExtractedDocument(blocks=()),
        language_code="en",
    )

    assert assessment.score == 0.0
    assert assessment.reason_codes == (EMPTY_DOCUMENT,)


def test_blank_blocks_lower_the_score_and_flag_a_reason_code() -> None:
    assessment = ShadowExtractionQualityGate().evaluate(
        document=make_document("first", "   ", "third", ""),
        language_code=None,
    )

    assert assessment.score == 0.5
    assert assessment.reason_codes == (EMPTY_BLOCK_TEXT,)
