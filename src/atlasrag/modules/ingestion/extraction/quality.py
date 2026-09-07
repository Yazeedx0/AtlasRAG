from atlasrag.contracts.types.extraction import (
    ExtractedDocument,
    ExtractionQualityAssessment,
)

EMPTY_DOCUMENT = "empty_document"
EMPTY_BLOCK_TEXT = "empty_block_text"


class ShadowExtractionQualityGate:
    def evaluate(
        self,
        *,
        document: ExtractedDocument,
        language_code: str | None,
    ) -> ExtractionQualityAssessment:
        _ = language_code
        if not document.blocks:
            return ExtractionQualityAssessment(
                score=0.0,
                reason_codes=(EMPTY_DOCUMENT,),
            )

        non_empty = sum(1 for block in document.blocks if block.text.strip())
        score = non_empty / len(document.blocks)
        reason_codes = () if non_empty == len(document.blocks) else (EMPTY_BLOCK_TEXT,)
        return ExtractionQualityAssessment(score=score, reason_codes=reason_codes)


__all__ = ["EMPTY_BLOCK_TEXT", "EMPTY_DOCUMENT", "ShadowExtractionQualityGate"]
