from collections.abc import Callable

from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)

from evals.chunking.contract import EvalChunk
from evals.chunking.metrics import (
    COMPARED_METRICS,
    METRIC_KINDS,
    ChunkQualityWarning,
    QualityThresholds,
    aggregate_observations,
    derive_warnings,
    metric_value,
    observe_chunks,
)
from evals.core.reporting import MetricKind
from evals.core.tokenization import Tokenizer

HEADING = ExtractedBlockType.HEADING
TABLE = ExtractedBlockType.TABLE
TABLE_TEXT = "| segment | 2025 |\n| --- | --- |\n| retail | 48200 |"


def _observe(
    *,
    document: ExtractedDocument,
    chunks: tuple[EvalChunk, ...],
    tokenizer: Tokenizer,
    thresholds: QualityThresholds = QualityThresholds(),
):
    return aggregate_observations(
        [
            observe_chunks(
                document=document,
                chunks=chunks,
                tokenizer=tokenizer,
                thresholds=thresholds,
            )
        ]
    )


def test_token_distribution_is_computed_from_chunk_texts(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("one two three four five"))
    chunks = (
        build_chunk("one two", ordinal=0),
        build_chunk("one two three four", ordinal=1),
        build_chunk("one two three four five six", ordinal=2),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.chunk_count == 3
    assert metrics.tokens.total_tokens == 12
    assert metrics.tokens.min_tokens == 2
    assert metrics.tokens.max_tokens == 6
    assert metrics.tokens.mean_tokens == 4.0
    assert metrics.tokens.median_tokens == 4.0


def test_p90_uses_nearest_rank_over_the_pooled_chunks(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("body"))
    chunks = tuple(
        build_chunk(" ".join(["token"] * size), ordinal=index)
        for index, size in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 40])
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.tokens.p90_tokens == 9.0


def test_empty_and_undersized_chunks_are_counted_separately(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("body"))
    chunks = (
        build_chunk("   ", ordinal=0),
        build_chunk("one two", ordinal=1),
        build_chunk(" ".join(["token"] * 12), ordinal=2),
    )

    metrics = _observe(
        document=document,
        chunks=chunks,
        tokenizer=tokenizer,
        thresholds=QualityThresholds(max_tokens=10, min_tokens=5),
    )

    assert metrics.empty_chunks == 1
    assert metrics.chunks_below_minimum_tokens == 1
    assert metrics.chunks_over_token_limit == 1


def test_duplicate_chunks_are_detected_ignoring_whitespace(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("body"))
    chunks = (
        build_chunk("annual leave is 21 days", ordinal=0),
        build_chunk("annual   leave is\n21 days", ordinal=1),
        build_chunk("sick leave is 14 days", ordinal=2),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.duplicate_content_chunks == 1
    assert metrics.distinct_content_hashes == 2


def test_heading_path_and_page_coverage_are_ratios_over_chunks(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("body"))
    chunks = (
        build_chunk("a", ordinal=0, heading_path=("Policy",), page_numbers=(1,)),
        build_chunk("b", ordinal=1, heading_path=("Policy",), page_numbers=()),
        build_chunk("c", ordinal=2, heading_path=(), page_numbers=(2,)),
        build_chunk("d", ordinal=3, heading_path=(), page_numbers=(2,)),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.heading_path_coverage == 0.5
    assert metrics.page_provenance_coverage == 0.75


def test_a_heading_is_preserved_when_its_text_survives_intact(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(
        build_block("Remote Work Eligibility", block_type=HEADING),
        build_block("Employees may request a remote arrangement after probation."),
    )
    chunks = (
        build_chunk(
            "Remote Work Eligibility\n\nEmployees may request a remote arrangement "
            "after probation.",
            ordinal=0,
        ),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.source_heading_count == 1
    assert metrics.headings_preserved == 1
    assert metrics.heading_preservation_rate == 1.0
    assert metrics.orphaned_headings == 0


def test_a_heading_carried_only_in_the_heading_path_still_counts_as_preserved(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(
        build_block("Access Control", block_type=HEADING),
        build_block("Passwords must be at least fourteen characters long."),
    )
    chunks = (
        build_chunk(
            "Passwords must be at least fourteen characters long.",
            ordinal=0,
            heading_path=("Access Control",),
        ),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.headings_preserved == 1
    assert metrics.orphaned_headings == 0


def test_a_heading_split_from_its_body_is_reported_as_orphaned(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(
        build_block("Home Office Equipment", block_type=HEADING),
        build_block(
            "The company reimburses up to one thousand two hundred dollars of equipment."
        ),
    )
    chunks = (
        build_chunk("Home Office Equipment", ordinal=0),
        build_chunk(
            "The company reimburses up to one thousand two hundred dollars of equipment.",
            ordinal=1,
        ),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.headings_preserved == 1
    assert metrics.orphaned_headings == 1


def test_a_heading_destroyed_by_a_mid_heading_split_is_not_preserved(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(
        build_block("Home Office Equipment Reimbursement", block_type=HEADING),
        build_block("Up to one thousand two hundred dollars."),
    )
    chunks = (
        build_chunk("Home Office", ordinal=0),
        build_chunk("Equipment Reimbursement Up to one thousand two hundred dollars.", ordinal=1),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.headings_preserved == 0
    assert metrics.heading_preservation_rate == 0.0


def test_an_intact_table_is_reported_as_preserved(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(
        build_block("Revenue", block_type=HEADING),
        build_block(TABLE_TEXT, block_type=TABLE),
    )
    chunks = (build_chunk(f"Revenue\n\n{TABLE_TEXT}", ordinal=0),)

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.source_table_count == 1
    assert metrics.tables_preserved == 1
    assert metrics.table_preservation_rate == 1.0


def test_a_table_split_across_chunks_is_not_preserved(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block(TABLE_TEXT, block_type=TABLE))
    halfway = len(TABLE_TEXT) // 2
    chunks = (
        build_chunk(TABLE_TEXT[:halfway], ordinal=0),
        build_chunk(TABLE_TEXT[halfway:], ordinal=1),
    )

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.tables_preserved == 0
    assert metrics.table_preservation_rate == 0.0


def test_rates_are_none_when_the_document_has_nothing_to_measure(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("Plain prose with no headings and no tables."))
    chunks = (build_chunk("Plain prose with no headings and no tables.", ordinal=0),)

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metrics.heading_preservation_rate is None
    assert metrics.table_preservation_rate is None


def test_aggregation_pools_chunks_across_documents(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    first = build_document(build_block("Alpha", block_type=HEADING), build_block("one two"))
    second = build_document(build_block("three four five"))

    observations = [
        observe_chunks(
            document=first,
            chunks=(build_chunk("Alpha one two", ordinal=0, heading_path=("Alpha",)),),
            tokenizer=tokenizer,
            thresholds=QualityThresholds(),
        ),
        observe_chunks(
            document=second,
            chunks=(build_chunk("three four five", ordinal=0),),
            tokenizer=tokenizer,
            thresholds=QualityThresholds(),
        ),
    ]

    metrics = aggregate_observations(observations)

    assert metrics.chunk_count == 2
    assert metrics.tokens.total_tokens == 6
    assert metrics.source_heading_count == 1
    assert metrics.heading_path_coverage == 0.5


def test_aggregation_of_nothing_yields_an_empty_but_valid_metric_set() -> None:
    metrics = aggregate_observations([])

    assert metrics.chunk_count == 0
    assert metrics.tokens.total_tokens == 0
    assert metrics.heading_path_coverage is None


def test_a_broken_chunk_set_raises_every_relevant_warning(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(
        build_block("Revenue Summary", block_type=HEADING),
        build_block(TABLE_TEXT, block_type=TABLE),
    )
    halfway = len(TABLE_TEXT) // 2
    chunks = (
        build_chunk("", ordinal=0),
        build_chunk("Revenue Summary", ordinal=1),
        build_chunk("Revenue Summary", ordinal=2),
        build_chunk(TABLE_TEXT[:halfway], ordinal=3),
        build_chunk(TABLE_TEXT[halfway:], ordinal=4),
        build_chunk(" ".join(["token"] * 40), ordinal=5),
    )

    metrics = _observe(
        document=document,
        chunks=chunks,
        tokenizer=tokenizer,
        thresholds=QualityThresholds(max_tokens=20, min_tokens=10),
    )
    warnings = derive_warnings(
        metrics=metrics, thresholds=QualityThresholds(max_tokens=20, min_tokens=10)
    )

    assert set(warnings) == {
        ChunkQualityWarning.EMPTY_CHUNKS,
        ChunkQualityWarning.CHUNKS_OVER_TOKEN_LIMIT,
        ChunkQualityWarning.EXCESSIVE_SMALL_CHUNKS,
        ChunkQualityWarning.DUPLICATE_CHUNK_CONTENT,
        ChunkQualityWarning.MISSING_PAGE_PROVENANCE,
        ChunkQualityWarning.TABLE_CONTENT_SPLIT,
        ChunkQualityWarning.ORPHANED_HEADING,
    }


def test_a_healthy_chunk_set_raises_no_warnings(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(
        build_block("Revenue Summary", block_type=HEADING),
        build_block(TABLE_TEXT, block_type=TABLE),
    )
    chunks = (
        build_chunk(
            f"Revenue Summary\n\n{TABLE_TEXT}",
            ordinal=0,
            heading_path=("Revenue Summary",),
            page_numbers=(12,),
        ),
    )

    thresholds = QualityThresholds(max_tokens=100, min_tokens=5)
    metrics = _observe(
        document=document, chunks=chunks, tokenizer=tokenizer, thresholds=thresholds
    )

    assert derive_warnings(metrics=metrics, thresholds=thresholds) == ()


def test_no_chunks_produced_is_reported_on_its_own() -> None:
    metrics = aggregate_observations([])

    assert derive_warnings(metrics=metrics, thresholds=QualityThresholds()) == (
        ChunkQualityWarning.NO_CHUNKS_PRODUCED,
    )


def test_warnings_are_ordered_deterministically(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("body"))
    chunks = (build_chunk("", ordinal=0), build_chunk("", ordinal=1))
    thresholds = QualityThresholds()

    metrics = _observe(
        document=document, chunks=chunks, tokenizer=tokenizer, thresholds=thresholds
    )
    warnings = derive_warnings(metrics=metrics, thresholds=thresholds)

    assert warnings == tuple(sorted(warnings))


def test_every_compared_metric_declares_a_kind() -> None:
    assert set(COMPARED_METRICS) <= set(METRIC_KINDS)


def test_structure_inference_metrics_are_labelled_heuristic() -> None:
    assert METRIC_KINDS["heading_preservation_rate"] is MetricKind.HEURISTIC
    assert METRIC_KINDS["orphaned_headings"] is MetricKind.HEURISTIC
    assert METRIC_KINDS["table_preservation_rate"] is MetricKind.HEURISTIC


def test_counting_metrics_are_labelled_objective() -> None:
    assert METRIC_KINDS["chunk_count"] is MetricKind.OBJECTIVE
    assert METRIC_KINDS["heading_path_coverage"] is MetricKind.OBJECTIVE
    assert METRIC_KINDS["page_provenance_coverage"] is MetricKind.OBJECTIVE


def test_metric_value_reads_both_flat_and_nested_names(
    tokenizer: Tokenizer,
    build_block: Callable[..., ExtractedBlock],
    build_document: Callable[..., ExtractedDocument],
    build_chunk: Callable[..., EvalChunk],
) -> None:
    document = build_document(build_block("one two three"))
    chunks = (build_chunk("one two three", ordinal=0),)

    metrics = _observe(document=document, chunks=chunks, tokenizer=tokenizer)

    assert metric_value(metrics, "chunk_count") == 1.0
    assert metric_value(metrics, "tokens.total_tokens") == 3.0
    assert metric_value(metrics, "table_preservation_rate") is None
