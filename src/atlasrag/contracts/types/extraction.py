from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

_EMPTY_METADATA: Mapping[str, object] = MappingProxyType({})


class ExtractedBlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"
    CODE = "code"
    OTHER = "other"


class ExtractionMethod(StrEnum):
    OPENAI_OCR = "openai_ocr"
    VLM = "vlm"


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    text: str
    block_type: ExtractedBlockType
    page_number: int | None = None
    metadata: Mapping[str, object] = _EMPTY_METADATA


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    blocks: tuple[ExtractedBlock, ...]
    metadata: Mapping[str, object] = _EMPTY_METADATA


@dataclass(frozen=True, slots=True)
class ExtractionQualityAssessment:
    score: float
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    document: ExtractedDocument
    method: ExtractionMethod
    fallback_used: bool
    fallback_reason: str | None
    quality_score: float | None


__all__ = [
    "ExtractedBlock",
    "ExtractedBlockType",
    "ExtractedDocument",
    "ExtractionMethod",
    "ExtractionQualityAssessment",
    "ExtractionResult",
]
