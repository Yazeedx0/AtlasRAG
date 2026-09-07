from atlasrag.contracts.types.chunking import ChunkContentType, ChunkingStrategy
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)
from atlasrag.modules.ingestion.chunking.heading_aware import HeadingAwareChunker
from atlasrag.modules.ingestion.chunking.tokenizer import ReferenceTextTokenizer

TOKENIZER = ReferenceTextTokenizer()

ARABIC_HEADING = "سياسة الإجازات"
ARABIC_SUBHEADING = "الإجازة السنوية"
ARABIC_BODY = "يحق للموظف الحصول على إجازة سنوية مدفوعة الأجر."


def make_document(*blocks: ExtractedBlock) -> ExtractedDocument:
    return ExtractedDocument(blocks=blocks)


def heading(
    text: str,
    *,
    level: int | None = None,
    page_number: int | None = None,
) -> ExtractedBlock:
    metadata = {"level": level} if level is not None else {}
    return ExtractedBlock(
        text=text,
        block_type=ExtractedBlockType.HEADING,
        page_number=page_number,
        metadata=metadata,
    )


def paragraph(text: str, *, page_number: int | None = None) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        block_type=ExtractedBlockType.PARAGRAPH,
        page_number=page_number,
    )


def table(text: str, *, page_number: int | None = None) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        block_type=ExtractedBlockType.TABLE,
        page_number=page_number,
    )


def code(text: str, *, page_number: int | None = None) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        block_type=ExtractedBlockType.CODE,
        page_number=page_number,
    )


def make_chunker(*, max_tokens: int = 200, overlap_tokens: int = 10) -> HeadingAwareChunker:
    return HeadingAwareChunker(
        tokenizer=TOKENIZER,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )


def long_paragraph(word_count: int, *, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{index}" for index in range(word_count))


def markdown_table(row_count: int) -> str:
    rows = "\n".join(f"| item-{index} | value-{index} |" for index in range(1, row_count + 1))
    return f"| Item | Value |\n|---|---|\n{rows}"


def test_heading_hierarchy_builds_the_section_path() -> None:
    document = make_document(
        heading("Handbook", level=1),
        heading("Leave", level=2),
        paragraph("Employees accrue leave monthly."),
    )

    chunks = make_chunker().chunk(document=document)

    assert chunks[0].section_path == ("Handbook", "Leave")
    assert chunks[0].section_title == "Leave"


def test_sibling_heading_replaces_the_previous_section_at_the_same_level() -> None:
    document = make_document(
        heading("Handbook", level=1),
        heading("Leave", level=2),
        paragraph("Leave body."),
        heading("Payroll", level=2),
        paragraph("Payroll body."),
    )

    chunks = make_chunker().chunk(document=document)

    assert [chunk.section_path for chunk in chunks] == [
        ("Handbook", "Leave"),
        ("Handbook", "Payroll"),
    ]


def test_shallower_heading_unwinds_the_hierarchy() -> None:
    document = make_document(
        heading("Handbook", level=1),
        heading("Leave", level=2),
        heading("Annual", level=3),
        paragraph("Annual body."),
        heading("Appendix", level=1),
        paragraph("Appendix body."),
    )

    chunks = make_chunker().chunk(document=document)

    assert chunks[0].section_path == ("Handbook", "Leave", "Annual")
    assert chunks[1].section_path == ("Appendix",)


def test_markdown_heading_levels_are_inferred_without_metadata() -> None:
    document = make_document(
        ExtractedBlock(text="# Handbook", block_type=ExtractedBlockType.HEADING),
        ExtractedBlock(text="## Leave", block_type=ExtractedBlockType.HEADING),
        paragraph("Body."),
    )

    chunks = make_chunker().chunk(document=document)

    assert chunks[0].section_path == ("Handbook", "Leave")


def test_paragraphs_in_one_section_are_grouped_into_a_single_chunk() -> None:
    document = make_document(
        heading("Leave", level=1),
        paragraph("First paragraph."),
        paragraph("Second paragraph."),
        paragraph("Third paragraph."),
    )

    chunks = make_chunker().chunk(document=document)

    assert len(chunks) == 1
    assert "First paragraph." in chunks[0].content
    assert "Third paragraph." in chunks[0].content


def test_sections_are_never_merged_across_a_heading_boundary() -> None:
    document = make_document(
        heading("Leave", level=1),
        paragraph("Leave body."),
        heading("Payroll", level=1),
        paragraph("Payroll body."),
    )

    chunks = make_chunker().chunk(document=document)

    assert len(chunks) == 2
    assert "Payroll body." not in chunks[0].content


def test_oversized_section_is_split_within_the_token_bound() -> None:
    document = make_document(
        heading("Leave", level=1),
        paragraph(long_paragraph(40)),
        paragraph(long_paragraph(40, prefix="term")),
        paragraph(long_paragraph(40, prefix="item")),
    )

    chunks = make_chunker(max_tokens=60, overlap_tokens=10).chunk(document=document)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 60 for chunk in chunks)
    assert all(chunk.section_path == ("Leave",) for chunk in chunks)
    assert [chunk.metadata["part"] for chunk in chunks] == list(range(1, len(chunks) + 1))


def test_a_single_oversized_paragraph_is_split_by_tokens() -> None:
    document = make_document(
        heading("Leave", level=1),
        paragraph(long_paragraph(200)),
    )

    chunks = make_chunker(max_tokens=40, overlap_tokens=8).chunk(document=document)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 40 for chunk in chunks)


def test_split_sections_carry_forward_an_overlap() -> None:
    document = make_document(
        heading("Leave", level=1),
        paragraph(long_paragraph(100)),
    )

    chunks = make_chunker(max_tokens=40, overlap_tokens=8).chunk(document=document)

    assert chunks[1].content.split()[0] in chunks[0].content


def test_page_provenance_is_preserved_per_section() -> None:
    document = make_document(
        heading("Leave", level=1, page_number=2),
        paragraph("First.", page_number=2),
        paragraph("Second.", page_number=3),
    )

    chunks = make_chunker().chunk(document=document)

    assert chunks[0].page_start == 2
    assert chunks[0].page_end == 3


def test_output_is_deterministic() -> None:
    document = make_document(
        heading("Handbook", level=1),
        paragraph(long_paragraph(90)),
        table(markdown_table(8)),
        code("print('hello')"),
    )
    chunker = make_chunker(max_tokens=50, overlap_tokens=5)

    assert chunker.chunk(document=document) == chunker.chunk(document=document)


def test_no_empty_chunks_are_emitted() -> None:
    document = make_document(
        heading("Leave", level=1),
        paragraph("   "),
        paragraph("Body."),
        paragraph("\n\t "),
    )

    chunks = make_chunker().chunk(document=document)

    assert len(chunks) == 1
    assert chunks[0].content == "Body."


def test_chunk_indices_are_contiguous_across_mixed_content() -> None:
    document = make_document(
        heading("Handbook", level=1),
        paragraph("Prose."),
        table(markdown_table(3)),
        code("SELECT 1;"),
        heading("Appendix", level=1),
        paragraph("More prose."),
    )

    chunks = make_chunker().chunk(document=document)

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_arabic_document_is_chunked_with_its_own_hierarchy() -> None:
    document = make_document(
        heading(ARABIC_HEADING, level=1, page_number=1),
        heading(ARABIC_SUBHEADING, level=2, page_number=1),
        paragraph(ARABIC_BODY, page_number=1),
    )

    chunks = make_chunker().chunk(document=document, language_code="ar")

    assert len(chunks) == 1
    assert chunks[0].section_path == (ARABIC_HEADING, ARABIC_SUBHEADING)
    assert chunks[0].content == ARABIC_BODY
    assert chunks[0].language_code == "ar"


def test_oversized_arabic_section_respects_the_token_bound() -> None:
    body = " ".join([ARABIC_BODY] * 20)
    document = make_document(heading(ARABIC_HEADING, level=1), paragraph(body))

    chunks = make_chunker(max_tokens=40, overlap_tokens=8).chunk(
        document=document,
        language_code="ar",
    )

    assert len(chunks) > 1
    assert all(chunk.token_count <= 40 for chunk in chunks)
    assert all(chunk.section_path == (ARABIC_HEADING,) for chunk in chunks)


def test_content_types_follow_the_source_blocks() -> None:
    document = make_document(
        heading("Handbook", level=1),
        paragraph("Prose."),
        table(markdown_table(2)),
        code("SELECT 1;"),
    )

    chunks = make_chunker().chunk(document=document)

    assert [chunk.content_type for chunk in chunks] == [
        ChunkContentType.TEXT,
        ChunkContentType.TABLE,
        ChunkContentType.CODE,
    ]


def test_small_table_stays_in_one_chunk() -> None:
    document = make_document(
        heading("Rates", level=1),
        table(markdown_table(3), page_number=5),
    )

    chunks = make_chunker(max_tokens=200).chunk(document=document)

    assert len(chunks) == 1
    assert chunks[0].content_type is ChunkContentType.TABLE
    assert chunks[0].content == markdown_table(3)
    assert chunks[0].page_start == 5
    assert "part" not in chunks[0].metadata


def test_large_table_is_split_with_the_header_repeated() -> None:
    document = make_document(
        heading("Rates", level=1),
        table(markdown_table(12), page_number=5),
    )

    chunks = make_chunker(max_tokens=40, overlap_tokens=5).chunk(document=document)

    assert len(chunks) > 1
    assert all(chunk.content_type is ChunkContentType.TABLE for chunk in chunks)
    assert all(chunk.token_count <= 40 for chunk in chunks)
    assert all(chunk.content.startswith("| Item | Value |\n|---|---|") for chunk in chunks)
    assert all(chunk.metadata["table_header_repeated"] is True for chunk in chunks)
    assert all(chunk.section_path == ("Rates",) for chunk in chunks)


def test_split_table_preserves_every_data_row_exactly_once() -> None:
    document = make_document(table(markdown_table(12)))

    chunks = make_chunker(max_tokens=40, overlap_tokens=5).chunk(document=document)

    rows = [
        line
        for chunk in chunks
        for line in chunk.content.splitlines()
        if line.startswith("| item-")
    ]
    assert rows == [f"| item-{index} | value-{index} |" for index in range(1, 13)]


def test_table_is_not_merged_with_surrounding_paragraphs() -> None:
    document = make_document(
        heading("Rates", level=1),
        paragraph("Intro prose."),
        table(markdown_table(2)),
        paragraph("Outro prose."),
    )

    chunks = make_chunker(max_tokens=200).chunk(document=document)

    assert len(chunks) == 3
    assert chunks[1].content_type is ChunkContentType.TABLE
    assert "prose" not in chunks[1].content


def test_non_markdown_table_falls_back_to_token_windows() -> None:
    document = make_document(table(long_paragraph(120, prefix="cell")))

    chunks = make_chunker(max_tokens=30, overlap_tokens=5).chunk(document=document)

    assert len(chunks) > 1
    assert all(chunk.content_type is ChunkContentType.TABLE for chunk in chunks)
    assert all(chunk.token_count <= 30 for chunk in chunks)
    assert all(chunk.metadata["table_header_repeated"] is False for chunk in chunks)


def test_strategy_is_recorded_on_every_chunk() -> None:
    document = make_document(heading("Leave", level=1), paragraph("Body."))

    chunks = make_chunker().chunk(document=document)

    assert all(
        chunk.metadata["strategy"] == ChunkingStrategy.HEADING_AWARE_V1.value
        for chunk in chunks
    )


def test_content_without_headings_has_an_empty_section_path() -> None:
    document = make_document(paragraph("Standalone body."))

    chunks = make_chunker().chunk(document=document)

    assert chunks[0].section_path == ()
    assert chunks[0].section_title is None


def test_empty_document_produces_no_chunks() -> None:
    assert make_chunker().chunk(document=make_document()) == ()


def test_headings_without_body_content_produce_no_chunks() -> None:
    document = make_document(heading("Leave", level=1), heading("Payroll", level=1))

    assert make_chunker().chunk(document=document) == ()
