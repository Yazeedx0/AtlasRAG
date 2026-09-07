from dataclasses import dataclass
from enum import StrEnum

from atlasrag.contracts.types.extraction import ExtractedDocument

from evals.core.language import EvalLanguage

FIXTURE_SCHEMA_VERSION = "1"


class FixtureSourceType(StrEnum):
    PROSE = "prose"
    NESTED_HEADINGS = "nested_headings"
    TABLE_REPORT = "table_report"
    LONG_SECTION = "long_section"


@dataclass(frozen=True, slots=True)
class ExpectedStructure:
    heading_count: int
    table_count: int
    requires_splitting: bool
    pages_covered: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AnnotatedBoundary:
    after_block_index: int
    rationale: str


@dataclass(frozen=True, slots=True)
class EvalFixture:
    fixture_id: str
    title: str
    language: EvalLanguage
    source_type: FixtureSourceType
    document: ExtractedDocument
    expected_structure: ExpectedStructure
    annotated_boundaries: tuple[AnnotatedBoundary, ...]
    content_hash: str


@dataclass(frozen=True, slots=True)
class EvalDataset:
    dataset_id: str
    version: str
    fixtures: tuple[EvalFixture, ...]
    content_hash: str

    def by_language(self, language: EvalLanguage) -> tuple[EvalFixture, ...]:
        return tuple(fixture for fixture in self.fixtures if fixture.language is language)


__all__ = [
    "FIXTURE_SCHEMA_VERSION",
    "AnnotatedBoundary",
    "EvalDataset",
    "EvalFixture",
    "ExpectedStructure",
    "FixtureSourceType",
]
