from dataclasses import dataclass
from enum import StrEnum

from evals.core.language import EvalLanguage

GOLDEN_SCHEMA_VERSION = "1"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    ACCESS_RESTRICTED = "access_restricted"
    OUT_OF_SCOPE = "out_of_scope"


class GoldenCategory(StrEnum):
    SINGLE_HOP = "single_hop"
    MULTI_HOP = "multi_hop"
    TABLE_LOOKUP = "table_lookup"
    LITERAL_TERM = "literal_term"
    SEMANTIC_GAP = "semantic_gap"
    UNANSWERABLE = "unanswerable"
    PLANTED_CONFLICT = "planted_conflict"
    CROSS_LINGUAL = "cross_lingual"


@dataclass(frozen=True, slots=True)
class GoldenQuestion:
    question_id: str
    question: str
    language: EvalLanguage
    category: GoldenCategory
    expected_status: AnswerStatus
    ground_truth_answer: str | None
    relevant_chunk_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldenSet:
    dataset_id: str
    version: str
    questions: tuple[GoldenQuestion, ...]
    content_hash: str


__all__ = [
    "GOLDEN_SCHEMA_VERSION",
    "AnswerStatus",
    "GoldenCategory",
    "GoldenQuestion",
    "GoldenSet",
]
