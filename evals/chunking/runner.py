from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from evals.chunking.contract import ChunkingStrategy, EvalChunk, EvalChunker
from evals.chunking.metrics import (
    METRIC_KINDS,
    ChunkingMetrics,
    ChunkObservation,
    ChunkQualityWarning,
    QualityThresholds,
    aggregate_observations,
    derive_warnings,
    observe_chunks,
)
from evals.core.language import REPORTED_SUBSETS, EvalLanguage, MetricSubset, subset_accepts
from evals.core.reporting import (
    REPORT_SCHEMA_VERSION,
    DatasetIdentity,
    MetricKind,
    RunProvenance,
    fingerprint,
)
from evals.core.tokenization import Tokenizer, TokenizerIdentity
from evals.datasets.contract import EvalDataset, EvalFixture, FixtureSourceType


@dataclass(frozen=True, slots=True)
class FixtureResult:
    fixture_id: str
    language: EvalLanguage
    source_type: FixtureSourceType
    metrics: ChunkingMetrics
    warnings: tuple[ChunkQualityWarning, ...]
    repeatable: bool


@dataclass(frozen=True, slots=True)
class SubsetResult:
    subset: MetricSubset
    fixture_count: int
    metrics: ChunkingMetrics
    warnings: tuple[ChunkQualityWarning, ...]


@dataclass(frozen=True, slots=True)
class ChunkingEvaluation:
    strategy: ChunkingStrategy
    thresholds: QualityThresholds
    repeatable: bool
    fixtures: tuple[FixtureResult, ...]
    subsets: tuple[SubsetResult, ...]

    def subset(self, subset: MetricSubset) -> SubsetResult:
        for result in self.subsets:
            if result.subset is subset:
                return result
        raise KeyError(subset)


@dataclass(frozen=True, slots=True)
class ChunkingEvaluationReport:
    schema_version: str
    report_type: str
    dataset: DatasetIdentity
    tokenizer: TokenizerIdentity
    metric_kinds: Mapping[str, MetricKind]
    evaluation: ChunkingEvaluation
    fingerprint: str
    provenance: RunProvenance


def dataset_identity(dataset: EvalDataset) -> DatasetIdentity:
    return DatasetIdentity(
        dataset_id=dataset.dataset_id,
        version=dataset.version,
        content_hash=dataset.content_hash,
        fixture_count=len(dataset.fixtures),
    )


def _shape(chunks: Sequence[EvalChunk]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (chunk.ordinal, chunk.text, chunk.heading_path, chunk.page_numbers)
        for chunk in chunks
    )


def _evaluate_fixture(
    *,
    chunker: EvalChunker,
    fixture: EvalFixture,
    tokenizer: Tokenizer,
    thresholds: QualityThresholds,
) -> tuple[FixtureResult, ChunkObservation]:
    chunks = chunker.chunk(document=fixture.document)
    repeatable = _shape(chunks) == _shape(chunker.chunk(document=fixture.document))
    observation = observe_chunks(
        document=fixture.document,
        chunks=chunks,
        tokenizer=tokenizer,
        thresholds=thresholds,
    )
    metrics = aggregate_observations([observation])
    return (
        FixtureResult(
            fixture_id=fixture.fixture_id,
            language=fixture.language,
            source_type=fixture.source_type,
            metrics=metrics,
            warnings=derive_warnings(metrics=metrics, thresholds=thresholds),
            repeatable=repeatable,
        ),
        observation,
    )


def evaluate_chunker(
    *,
    chunker: EvalChunker,
    dataset: EvalDataset,
    tokenizer: Tokenizer,
    thresholds: QualityThresholds = QualityThresholds(),
) -> ChunkingEvaluation:
    results: list[FixtureResult] = []
    observations: dict[str, ChunkObservation] = {}
    for fixture in dataset.fixtures:
        result, observation = _evaluate_fixture(
            chunker=chunker,
            fixture=fixture,
            tokenizer=tokenizer,
            thresholds=thresholds,
        )
        results.append(result)
        observations[fixture.fixture_id] = observation

    subsets: list[SubsetResult] = []
    for subset in REPORTED_SUBSETS:
        members = [result for result in results if subset_accepts(subset, result.language)]
        metrics = aggregate_observations(
            [observations[result.fixture_id] for result in members]
        )
        subsets.append(
            SubsetResult(
                subset=subset,
                fixture_count=len(members),
                metrics=metrics,
                warnings=derive_warnings(metrics=metrics, thresholds=thresholds),
            )
        )

    return ChunkingEvaluation(
        strategy=chunker.strategy,
        thresholds=thresholds,
        repeatable=all(result.repeatable for result in results),
        fixtures=tuple(results),
        subsets=tuple(subsets),
    )


def build_report(
    *,
    evaluation: ChunkingEvaluation,
    dataset: EvalDataset,
    tokenizer: Tokenizer,
    provenance: RunProvenance = RunProvenance(),
) -> ChunkingEvaluationReport:
    report = ChunkingEvaluationReport(
        schema_version=REPORT_SCHEMA_VERSION,
        report_type="chunking_evaluation",
        dataset=dataset_identity(dataset),
        tokenizer=tokenizer.identity,
        metric_kinds=METRIC_KINDS,
        evaluation=evaluation,
        fingerprint="",
        provenance=provenance,
    )
    return replace(report, fingerprint=fingerprint(replace(report, provenance=RunProvenance())))


__all__ = [
    "ChunkingEvaluation",
    "ChunkingEvaluationReport",
    "FixtureResult",
    "SubsetResult",
    "build_report",
    "dataset_identity",
    "evaluate_chunker",
]
