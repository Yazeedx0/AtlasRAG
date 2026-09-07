import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from types import MappingProxyType

from atlasrag.contracts.types.extraction import ExtractedBlockType, ExtractedDocument

from evals.chunking.contract import EvalChunk
from evals.core._hashing import hash_text
from evals.core.reporting import MetricKind
from evals.core.tokenization import Tokenizer

_ATTACHMENT_TOKENS = 10
_RATIO_PRECISION = 4


class ChunkQualityWarning(StrEnum):
    NO_CHUNKS_PRODUCED = "no_chunks_produced"
    EMPTY_CHUNKS = "empty_chunks"
    CHUNKS_OVER_TOKEN_LIMIT = "chunks_over_token_limit"
    EXCESSIVE_SMALL_CHUNKS = "excessive_small_chunks"
    DUPLICATE_CHUNK_CONTENT = "duplicate_chunk_content"
    MISSING_PAGE_PROVENANCE = "missing_page_provenance"
    TABLE_CONTENT_SPLIT = "table_content_split"
    ORPHANED_HEADING = "orphaned_heading"


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    max_tokens: int = 256
    min_tokens: int = 32
    max_small_chunk_ratio: float = 0.25
    min_page_provenance_coverage: float = 0.9


@dataclass(frozen=True, slots=True)
class TokenDistribution:
    total_tokens: int
    min_tokens: int
    max_tokens: int
    mean_tokens: float
    median_tokens: float
    p90_tokens: float


@dataclass(frozen=True, slots=True)
class ChunkingMetrics:
    chunk_count: int
    empty_chunks: int
    chunks_over_token_limit: int
    chunks_below_minimum_tokens: int
    duplicate_content_chunks: int
    distinct_content_hashes: int
    tokens: TokenDistribution
    chunks_with_heading_path: int
    heading_path_coverage: float | None
    chunks_with_page_provenance: int
    page_provenance_coverage: float | None
    source_heading_count: int
    headings_preserved: int
    heading_preservation_rate: float | None
    orphaned_headings: int
    source_table_count: int
    tables_preserved: int
    table_preservation_rate: float | None


@dataclass(frozen=True, slots=True)
class ChunkObservation:
    token_counts: tuple[int, ...]
    content_hashes: tuple[str, ...]
    empty_chunks: int
    chunks_over_token_limit: int
    chunks_below_minimum_tokens: int
    chunks_with_heading_path: int
    chunks_with_page_provenance: int
    source_heading_count: int
    headings_preserved: int
    orphaned_headings: int
    source_table_count: int
    tables_preserved: int


METRIC_KINDS: Mapping[str, MetricKind] = MappingProxyType(
    {
        "chunk_count": MetricKind.OBJECTIVE,
        "empty_chunks": MetricKind.OBJECTIVE,
        "chunks_over_token_limit": MetricKind.OBJECTIVE,
        "chunks_below_minimum_tokens": MetricKind.OBJECTIVE,
        "duplicate_content_chunks": MetricKind.OBJECTIVE,
        "distinct_content_hashes": MetricKind.OBJECTIVE,
        "tokens.total_tokens": MetricKind.OBJECTIVE,
        "tokens.min_tokens": MetricKind.OBJECTIVE,
        "tokens.max_tokens": MetricKind.OBJECTIVE,
        "tokens.mean_tokens": MetricKind.OBJECTIVE,
        "tokens.median_tokens": MetricKind.OBJECTIVE,
        "tokens.p90_tokens": MetricKind.OBJECTIVE,
        "chunks_with_heading_path": MetricKind.OBJECTIVE,
        "heading_path_coverage": MetricKind.OBJECTIVE,
        "chunks_with_page_provenance": MetricKind.OBJECTIVE,
        "page_provenance_coverage": MetricKind.OBJECTIVE,
        "source_heading_count": MetricKind.OBJECTIVE,
        "headings_preserved": MetricKind.HEURISTIC,
        "heading_preservation_rate": MetricKind.HEURISTIC,
        "orphaned_headings": MetricKind.HEURISTIC,
        "source_table_count": MetricKind.OBJECTIVE,
        "tables_preserved": MetricKind.HEURISTIC,
        "table_preservation_rate": MetricKind.HEURISTIC,
    }
)

COMPARED_METRICS: tuple[str, ...] = (
    "chunk_count",
    "empty_chunks",
    "chunks_over_token_limit",
    "chunks_below_minimum_tokens",
    "duplicate_content_chunks",
    "tokens.mean_tokens",
    "tokens.median_tokens",
    "tokens.min_tokens",
    "tokens.max_tokens",
    "tokens.p90_tokens",
    "heading_path_coverage",
    "page_provenance_coverage",
    "heading_preservation_rate",
    "orphaned_headings",
    "table_preservation_rate",
)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, _RATIO_PRECISION)


def _percentile(values: Sequence[int], quantile: float) -> float:
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, ceil(quantile * len(ordered)) - 1))
    return float(ordered[rank])


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _contains(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    if not needle:
        return False
    limit = len(haystack) - len(needle)
    for start in range(limit + 1):
        if list(haystack[start : start + len(needle)]) == list(needle):
            return True
    return False


def _following_body_index(document: ExtractedDocument, heading_index: int) -> int | None:
    for index in range(heading_index + 1, len(document.blocks)):
        if document.blocks[index].block_type is not ExtractedBlockType.HEADING:
            return index
    return None


def observe_chunks(
    *,
    document: ExtractedDocument,
    chunks: Sequence[EvalChunk],
    tokenizer: Tokenizer,
    thresholds: QualityThresholds,
) -> ChunkObservation:
    chunk_tokens = [tokenizer.tokenize(chunk.text) for chunk in chunks]
    token_counts = tuple(len(tokens) for tokens in chunk_tokens)
    content_hashes = tuple(hash_text(_normalize(chunk.text)) for chunk in chunks)

    empty_chunks = sum(1 for chunk in chunks if not chunk.text.strip())
    over_limit = sum(1 for count in token_counts if count > thresholds.max_tokens)
    below_minimum = sum(1 for count in token_counts if 0 < count < thresholds.min_tokens)
    with_heading_path = sum(1 for chunk in chunks if chunk.heading_path)
    with_page_provenance = sum(1 for chunk in chunks if chunk.page_numbers)

    heading_indexes = [
        index
        for index, block in enumerate(document.blocks)
        if block.block_type is ExtractedBlockType.HEADING
    ]
    headings_preserved = 0
    orphaned_headings = 0
    for heading_index in heading_indexes:
        heading_text = document.blocks[heading_index].text
        heading_tokens = tokenizer.tokenize(heading_text)
        carrying = [
            position
            for position, chunk in enumerate(chunks)
            if heading_text in chunk.heading_path
            or _contains(chunk_tokens[position], heading_tokens)
        ]
        if not carrying:
            continue
        headings_preserved += 1
        body_index = _following_body_index(document, heading_index)
        if body_index is None:
            continue
        body_tokens = tokenizer.tokenize(document.blocks[body_index].text)
        attachment = body_tokens[:_ATTACHMENT_TOKENS]
        if not any(_contains(chunk_tokens[position], attachment) for position in carrying):
            orphaned_headings += 1

    table_indexes = [
        index
        for index, block in enumerate(document.blocks)
        if block.block_type is ExtractedBlockType.TABLE
    ]
    tables_preserved = 0
    for table_index in table_indexes:
        table_tokens = tokenizer.tokenize(document.blocks[table_index].text)
        if any(_contains(tokens, table_tokens) for tokens in chunk_tokens):
            tables_preserved += 1

    return ChunkObservation(
        token_counts=token_counts,
        content_hashes=content_hashes,
        empty_chunks=empty_chunks,
        chunks_over_token_limit=over_limit,
        chunks_below_minimum_tokens=below_minimum,
        chunks_with_heading_path=with_heading_path,
        chunks_with_page_provenance=with_page_provenance,
        source_heading_count=len(heading_indexes),
        headings_preserved=headings_preserved,
        orphaned_headings=orphaned_headings,
        source_table_count=len(table_indexes),
        tables_preserved=tables_preserved,
    )


def aggregate_observations(observations: Sequence[ChunkObservation]) -> ChunkingMetrics:
    token_counts: list[int] = []
    content_hashes: list[str] = []
    for observation in observations:
        token_counts.extend(observation.token_counts)
        content_hashes.extend(observation.content_hashes)

    chunk_count = len(token_counts)
    distinct_hashes = len(set(content_hashes))
    distribution = TokenDistribution(
        total_tokens=sum(token_counts),
        min_tokens=min(token_counts) if token_counts else 0,
        max_tokens=max(token_counts) if token_counts else 0,
        mean_tokens=round(statistics.fmean(token_counts), _RATIO_PRECISION)
        if token_counts
        else 0.0,
        median_tokens=round(statistics.median(token_counts), _RATIO_PRECISION)
        if token_counts
        else 0.0,
        p90_tokens=_percentile(token_counts, 0.9) if token_counts else 0.0,
    )

    with_heading_path = sum(item.chunks_with_heading_path for item in observations)
    with_page_provenance = sum(item.chunks_with_page_provenance for item in observations)
    source_headings = sum(item.source_heading_count for item in observations)
    headings_preserved = sum(item.headings_preserved for item in observations)
    source_tables = sum(item.source_table_count for item in observations)
    tables_preserved = sum(item.tables_preserved for item in observations)

    return ChunkingMetrics(
        chunk_count=chunk_count,
        empty_chunks=sum(item.empty_chunks for item in observations),
        chunks_over_token_limit=sum(item.chunks_over_token_limit for item in observations),
        chunks_below_minimum_tokens=sum(
            item.chunks_below_minimum_tokens for item in observations
        ),
        duplicate_content_chunks=chunk_count - distinct_hashes,
        distinct_content_hashes=distinct_hashes,
        tokens=distribution,
        chunks_with_heading_path=with_heading_path,
        heading_path_coverage=_ratio(with_heading_path, chunk_count),
        chunks_with_page_provenance=with_page_provenance,
        page_provenance_coverage=_ratio(with_page_provenance, chunk_count),
        source_heading_count=source_headings,
        headings_preserved=headings_preserved,
        heading_preservation_rate=_ratio(headings_preserved, source_headings),
        orphaned_headings=sum(item.orphaned_headings for item in observations),
        source_table_count=source_tables,
        tables_preserved=tables_preserved,
        table_preservation_rate=_ratio(tables_preserved, source_tables),
    )


def derive_warnings(
    *, metrics: ChunkingMetrics, thresholds: QualityThresholds
) -> tuple[ChunkQualityWarning, ...]:
    warnings: set[ChunkQualityWarning] = set()
    if metrics.chunk_count == 0:
        return (ChunkQualityWarning.NO_CHUNKS_PRODUCED,)
    if metrics.empty_chunks:
        warnings.add(ChunkQualityWarning.EMPTY_CHUNKS)
    if metrics.chunks_over_token_limit:
        warnings.add(ChunkQualityWarning.CHUNKS_OVER_TOKEN_LIMIT)
    if metrics.duplicate_content_chunks:
        warnings.add(ChunkQualityWarning.DUPLICATE_CHUNK_CONTENT)
    if metrics.orphaned_headings:
        warnings.add(ChunkQualityWarning.ORPHANED_HEADING)
    small_ratio = metrics.chunks_below_minimum_tokens / metrics.chunk_count
    if small_ratio > thresholds.max_small_chunk_ratio:
        warnings.add(ChunkQualityWarning.EXCESSIVE_SMALL_CHUNKS)
    coverage = metrics.page_provenance_coverage
    if coverage is not None and coverage < thresholds.min_page_provenance_coverage:
        warnings.add(ChunkQualityWarning.MISSING_PAGE_PROVENANCE)
    if metrics.source_table_count and metrics.tables_preserved < metrics.source_table_count:
        warnings.add(ChunkQualityWarning.TABLE_CONTENT_SPLIT)
    return tuple(sorted(warnings))


def metric_value(metrics: ChunkingMetrics, name: str) -> float | None:
    if name.startswith("tokens."):
        return float(getattr(metrics.tokens, name.removeprefix("tokens.")))
    value = getattr(metrics, name)
    return None if value is None else float(value)


__all__ = [
    "COMPARED_METRICS",
    "METRIC_KINDS",
    "ChunkObservation",
    "ChunkQualityWarning",
    "ChunkingMetrics",
    "QualityThresholds",
    "TokenDistribution",
    "aggregate_observations",
    "derive_warnings",
    "metric_value",
    "observe_chunks",
]
