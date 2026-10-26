from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from evals.chunking.metrics import (
    COMPARED_METRICS,
    METRIC_KINDS,
    QualityThresholds,
    metric_value,
)
from evals.chunking.runner import (
    ChunkingEvaluation,
    dataset_identity,
    evaluate_chunker,
)
from evals.chunking.contract import EvalChunker
from evals.core.language import REPORTED_SUBSETS, MetricSubset
from evals.core.reporting import (
    REPORT_SCHEMA_VERSION,
    DatasetIdentity,
    MetricKind,
    RunProvenance,
    fingerprint,
)
from evals.core.tokenization import Tokenizer, TokenizerIdentity
from evals.datasets.contract import EvalDataset

_DELTA_PRECISION = 4


@dataclass(frozen=True, slots=True)
class MetricDelta:
    metric: str
    kind: MetricKind
    subset: MetricSubset
    baseline_value: float | None
    candidate_value: float | None
    delta: float | None


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    evaluation: ChunkingEvaluation
    deltas: tuple[MetricDelta, ...]


@dataclass(frozen=True, slots=True)
class StrategyComparisonReport:
    schema_version: str
    report_type: str
    dataset: DatasetIdentity
    tokenizer: TokenizerIdentity
    thresholds: QualityThresholds
    metric_kinds: Mapping[str, MetricKind]
    baseline: ChunkingEvaluation
    candidates: tuple[CandidateComparison, ...]
    fingerprint: str
    provenance: RunProvenance


def _deltas(
    *, baseline: ChunkingEvaluation, candidate: ChunkingEvaluation
) -> tuple[MetricDelta, ...]:
    deltas: list[MetricDelta] = []
    for subset in REPORTED_SUBSETS:
        baseline_metrics = baseline.subset(subset).metrics
        candidate_metrics = candidate.subset(subset).metrics
        for name in COMPARED_METRICS:
            baseline_value = metric_value(baseline_metrics, name)
            candidate_value = metric_value(candidate_metrics, name)
            difference = (
                None
                if baseline_value is None or candidate_value is None
                else round(candidate_value - baseline_value, _DELTA_PRECISION)
            )
            deltas.append(
                MetricDelta(
                    metric=name,
                    kind=METRIC_KINDS[name],
                    subset=subset,
                    baseline_value=baseline_value,
                    candidate_value=candidate_value,
                    delta=difference,
                )
            )
    return tuple(deltas)


def compare_chunkers(
    *,
    baseline: EvalChunker,
    candidates: Sequence[EvalChunker],
    dataset: EvalDataset,
    tokenizer: Tokenizer,
    thresholds: QualityThresholds = QualityThresholds(),
    provenance: RunProvenance = RunProvenance(),
) -> StrategyComparisonReport:
    baseline_evaluation = evaluate_chunker(
        chunker=baseline, dataset=dataset, tokenizer=tokenizer, thresholds=thresholds
    )
    comparisons = tuple(
        CandidateComparison(
            evaluation=evaluation,
            deltas=_deltas(baseline=baseline_evaluation, candidate=evaluation),
        )
        for evaluation in (
            evaluate_chunker(
                chunker=candidate,
                dataset=dataset,
                tokenizer=tokenizer,
                thresholds=thresholds,
            )
            for candidate in candidates
        )
    )
    report = StrategyComparisonReport(
        schema_version=REPORT_SCHEMA_VERSION,
        report_type="chunking_strategy_comparison",
        dataset=dataset_identity(dataset),
        tokenizer=tokenizer.identity,
        thresholds=thresholds,
        metric_kinds=METRIC_KINDS,
        baseline=baseline_evaluation,
        candidates=comparisons,
        fingerprint="",
        provenance=provenance,
    )
    return replace(report, fingerprint=fingerprint(replace(report, provenance=RunProvenance())))


def _format_value(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value == int(value):
        return str(int(value))
    return f"{value:.4g}"


def _strategy_label(evaluation: ChunkingEvaluation) -> str:
    return f"{evaluation.strategy.name}-v{evaluation.strategy.version}"


def render_comparison_text(report: StrategyComparisonReport) -> str:
    lines: list[str] = []
    lines.append(f"dataset      : {report.dataset.dataset_id} v{report.dataset.version}")
    lines.append(f"dataset hash : {report.dataset.content_hash[:16]}")
    lines.append(
        f"tokenizer    : {report.tokenizer.name} v{report.tokenizer.version}"
        f" ({report.tokenizer.encoding or 'n/a'})"
    )
    lines.append(f"fingerprint  : {report.fingerprint[:16]}")
    lines.append("")

    evaluations = [report.baseline, *(item.evaluation for item in report.candidates)]
    labels = [_strategy_label(evaluation) for evaluation in evaluations]
    width = max(len(label) for label in labels)

    for evaluation, label in zip(evaluations, labels, strict=True):
        warnings = sorted(
            {warning for result in evaluation.fixtures for warning in result.warnings}
        )
        lines.append(f"{label:<{width}}  repeatable={evaluation.repeatable}")
        lines.append(f"{'':<{width}}  config={dict(evaluation.strategy.configuration)}")
        lines.append(
            f"{'':<{width}}  warnings={[str(warning) for warning in warnings] or 'none'}"
        )
    lines.append("")

    metric_width = max(len(name) for name in COMPARED_METRICS)
    for subset in REPORTED_SUBSETS:
        lines.append(f"[{subset}]")
        header = f"{'metric':<{metric_width}}  {'kind':<9}" + "".join(
            f"  {label:>{max(width, 12)}}" for label in labels
        )
        lines.append(header)
        lines.append("-" * len(header))
        for name in COMPARED_METRICS:
            cells = "".join(
                f"  {_format_value(metric_value(evaluation.subset(subset).metrics, name)):>{max(width, 12)}}"
                for evaluation in evaluations
            )
            lines.append(f"{name:<{metric_width}}  {METRIC_KINDS[name]:<9}{cells}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "CandidateComparison",
    "MetricDelta",
    "StrategyComparisonReport",
    "compare_chunkers",
    "render_comparison_text",
]
