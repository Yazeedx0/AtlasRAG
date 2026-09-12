from atlasrag.contracts.types.chunking import ChunkContentType
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)
from atlasrag.modules.ingestion.chunking.chunkers import FixedTokenChunker, HeadingAwareChunker
from atlasrag.modules.ingestion.chunking.config import ChunkingConfig, ChunkingStrategy
from atlasrag.modules.ingestion.chunking.tokenizer import WhitespaceReferenceTokenizer


def make_config(
    *,
    strategy: ChunkingStrategy,
    max_tokens: int = 5,
    overlap_tokens: int = 1,
) -> ChunkingConfig:
    return ChunkingConfig(
        strategy=strategy,
        reference_tokenizer="whitespace",
        reference_tokenizer_version="v1",
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        preserve_tables=True,
    )


def test_fixed_token_chunker_respects_limit_overlap_and_deterministic_hashes() -> None:
    chunker = FixedTokenChunker(
        tokenizer=WhitespaceReferenceTokenizer(),
        config=make_config(strategy=ChunkingStrategy.FIXED_TOKEN_V1),
    )
    document = ExtractedDocument(
        blocks=(
            ExtractedBlock(
                text="one two three four five six seven eight",
                block_type=ExtractedBlockType.PARAGRAPH,
                page_number=2,
            ),
        )
    )

    first = chunker.chunk(document=document, language_code="en")
    second = chunker.chunk(document=document, language_code="en")

    assert [chunk.content for chunk in first] == [
        "one two three four five",
        "five six seven eight",
    ]
    assert [chunk.token_count for chunk in first] == [5, 4]
    assert [chunk.chunk_index for chunk in first] == [0, 1]
    assert all(chunk.page_start == 2 and chunk.page_end == 2 for chunk in first)
    assert first == second


def test_fixed_token_chunker_returns_no_chunks_for_empty_document() -> None:
    chunker = FixedTokenChunker(
        tokenizer=WhitespaceReferenceTokenizer(),
        config=make_config(strategy=ChunkingStrategy.FIXED_TOKEN_V1),
    )

    assert chunker.chunk(document=ExtractedDocument(blocks=())) == ()


def test_heading_aware_chunker_preserves_section_boundaries_and_provenance() -> None:
    chunker = HeadingAwareChunker(
        tokenizer=WhitespaceReferenceTokenizer(),
        config=make_config(strategy=ChunkingStrategy.HEADING_AWARE_V1, max_tokens=10),
    )
    document = ExtractedDocument(
        blocks=(
            ExtractedBlock("Benefits", ExtractedBlockType.HEADING, page_number=12),
            ExtractedBlock(
                "Annual leave is available.",
                ExtractedBlockType.PARAGRAPH,
                page_number=12,
            ),
            ExtractedBlock("Carry Over", ExtractedBlockType.HEADING, page_number=13),
            ExtractedBlock(
                "Up to five days carry over.",
                ExtractedBlockType.PARAGRAPH,
                page_number=13,
            ),
        )
    )

    chunks = chunker.chunk(document=document, language_code="en")

    assert [chunk.section_path for chunk in chunks] == [("Benefits",), ("Carry Over",)]
    assert [chunk.section_title for chunk in chunks] == ["Benefits", "Carry Over"]
    assert [chunk.page_start for chunk in chunks] == [12, 13]
    assert [chunk.content_type for chunk in chunks] == [
        ChunkContentType.TEXT,
        ChunkContentType.TEXT,
    ]


def test_heading_aware_chunker_keeps_small_table_as_one_table_chunk() -> None:
    chunker = HeadingAwareChunker(
        tokenizer=WhitespaceReferenceTokenizer(),
        config=make_config(strategy=ChunkingStrategy.HEADING_AWARE_V1, max_tokens=20),
    )
    document = ExtractedDocument(
        blocks=(
            ExtractedBlock("Leave", ExtractedBlockType.HEADING, page_number=4),
            ExtractedBlock(
                "| Grade | Days |\n| --- | --- |\n| A | 20 |\n| B | 25 |",
                ExtractedBlockType.TABLE,
                page_number=4,
            ),
        )
    )

    chunks = chunker.chunk(document=document)

    assert len(chunks) == 1
    assert chunks[0].content_type is ChunkContentType.TABLE
    assert chunks[0].section_path == ("Leave",)


def test_heading_aware_chunker_splits_large_markdown_table_with_repeated_header() -> None:
    chunker = HeadingAwareChunker(
        tokenizer=WhitespaceReferenceTokenizer(),
        config=make_config(strategy=ChunkingStrategy.HEADING_AWARE_V1, max_tokens=16),
    )
    table = "\n".join(
        (
            "| Grade | Days |",
            "| --- | --- |",
            "| A | twenty |",
            "| B | twenty five |",
            "| C | thirty |",
        )
    )
    document = ExtractedDocument(
        blocks=(ExtractedBlock(table, ExtractedBlockType.TABLE, page_number=8),)
    )

    chunks = chunker.chunk(document=document)

    assert len(chunks) == 3
    assert all(chunk.content.startswith("| Grade | Days |\n| --- | --- |") for chunk in chunks)
    assert all(chunk.content_type is ChunkContentType.TABLE for chunk in chunks)
    assert all(chunk.token_count <= 16 for chunk in chunks)


def test_heading_aware_chunker_handles_arabic_deterministically() -> None:
    chunker = HeadingAwareChunker(
        tokenizer=WhitespaceReferenceTokenizer(),
        config=make_config(strategy=ChunkingStrategy.HEADING_AWARE_V1, max_tokens=4),
    )
    document = ExtractedDocument(
        blocks=(
            ExtractedBlock("الإجازة", ExtractedBlockType.HEADING, page_number=1),
            ExtractedBlock(
                "يستحق الموظف إجازة سنوية مدفوعة الأجر",
                ExtractedBlockType.PARAGRAPH,
                page_number=1,
            ),
        )
    )

    chunks = chunker.chunk(document=document, language_code="ar")

    assert [chunk.language_code for chunk in chunks] == ["ar", "ar"]
    assert [chunk.section_path for chunk in chunks] == [("الإجازة",), ("الإجازة",)]
