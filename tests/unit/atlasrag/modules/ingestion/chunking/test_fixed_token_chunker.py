import pytest

from atlasrag.contracts.types.chunking import ChunkContentType, ChunkingStrategy
from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)
from atlasrag.modules.ingestion.chunking.fixed_token import FixedTokenChunker
from atlasrag.modules.ingestion.chunking.tokenizer import ReferenceTextTokenizer

TOKENIZER = ReferenceTextTokenizer()


def make_document(*blocks: ExtractedBlock) -> ExtractedDocument:
    return ExtractedDocument(blocks=blocks)


def paragraph(text: str, *, page_number: int | None = None) -> ExtractedBlock:
    return ExtractedBlock(
        text=text,
        block_type=ExtractedBlockType.PARAGRAPH,
        page_number=page_number,
    )


def long_paragraph(word_count: int, *, prefix: str = "word") -> str:
    return " ".join(f"{prefix}{index}" for index in range(word_count))


def test_output_is_deterministic() -> None:
    document = make_document(
        paragraph(long_paragraph(80), page_number=1),
        paragraph(long_paragraph(80, prefix="term"), page_number=2),
    )
    chunker = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=40, overlap_tokens=8)

    assert chunker.chunk(document=document) == chunker.chunk(document=document)


def test_chunk_indices_are_stable_and_contiguous() -> None:
    document = make_document(paragraph(long_paragraph(200), page_number=1))

    chunks = FixedTokenChunker(
        tokenizer=TOKENIZER,
        max_tokens=25,
        overlap_tokens=5,
    ).chunk(document=document)

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunks_respect_the_token_bound() -> None:
    document = make_document(paragraph(long_paragraph(200), page_number=1))

    chunks = FixedTokenChunker(
        tokenizer=TOKENIZER,
        max_tokens=30,
        overlap_tokens=6,
    ).chunk(document=document)

    assert all(chunk.token_count <= 30 for chunk in chunks)
    assert all(chunk.token_count == TOKENIZER.count_tokens(chunk.content) for chunk in chunks)


def test_consecutive_chunks_share_the_configured_overlap() -> None:
    document = make_document(paragraph(long_paragraph(120), page_number=1))

    chunks = FixedTokenChunker(
        tokenizer=TOKENIZER,
        max_tokens=20,
        overlap_tokens=5,
    ).chunk(document=document)

    first_tail = TOKENIZER.split_tokens(chunks[0].content)[-5:]
    second_head = TOKENIZER.split_tokens(chunks[1].content)[:5]

    assert "".join(first_tail).strip() == "".join(second_head).strip()


def test_zero_overlap_produces_disjoint_chunks() -> None:
    document = make_document(paragraph(long_paragraph(60), page_number=1))

    chunks = FixedTokenChunker(
        tokenizer=TOKENIZER,
        max_tokens=20,
        overlap_tokens=0,
    ).chunk(document=document)

    rejoined = " ".join(chunk.content for chunk in chunks)
    assert rejoined.split() == long_paragraph(60).split()


def test_no_empty_chunks_are_emitted() -> None:
    document = make_document(
        paragraph("   "),
        paragraph("real content here"),
        paragraph("\n\n"),
    )

    chunks = FixedTokenChunker(
        tokenizer=TOKENIZER,
        max_tokens=40,
        overlap_tokens=0,
    ).chunk(document=document)

    assert len(chunks) == 1
    assert chunks[0].content == "real content here"


def test_empty_document_produces_no_chunks() -> None:
    assert FixedTokenChunker(tokenizer=TOKENIZER).chunk(document=make_document()) == ()


def test_page_provenance_spans_the_covered_blocks() -> None:
    document = make_document(
        paragraph(long_paragraph(10), page_number=4),
        paragraph(long_paragraph(10, prefix="term"), page_number=7),
    )

    chunks = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=200).chunk(document=document)

    assert chunks[0].page_start == 4
    assert chunks[0].page_end == 7


def test_missing_page_numbers_are_preserved_as_none() -> None:
    document = make_document(paragraph("content without page provenance"))

    chunks = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=200).chunk(document=document)

    assert chunks[0].page_start is None
    assert chunks[0].page_end is None


def test_content_hash_is_deterministic_and_content_dependent() -> None:
    first = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=200).chunk(
        document=make_document(paragraph("stable content"))
    )
    same = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=200).chunk(
        document=make_document(paragraph("stable content"))
    )
    different = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=200).chunk(
        document=make_document(paragraph("other content"))
    )

    assert first[0].content_hash == same[0].content_hash
    assert first[0].content_hash != different[0].content_hash


def test_uniform_table_window_keeps_the_table_content_type() -> None:
    document = make_document(
        ExtractedBlock(
            text="| a | b |\n|---|---|\n| 1 | 2 |",
            block_type=ExtractedBlockType.TABLE,
            page_number=1,
        )
    )

    chunks = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=200).chunk(document=document)

    assert chunks[0].content_type is ChunkContentType.TABLE


def test_mixed_window_falls_back_to_text() -> None:
    document = make_document(
        paragraph("prose"),
        ExtractedBlock(
            text="| a | b |",
            block_type=ExtractedBlockType.TABLE,
        ),
    )

    chunks = FixedTokenChunker(tokenizer=TOKENIZER, max_tokens=200).chunk(document=document)

    assert chunks[0].content_type is ChunkContentType.TEXT


def test_language_code_and_strategy_are_recorded() -> None:
    chunks = FixedTokenChunker(tokenizer=TOKENIZER).chunk(
        document=make_document(paragraph("محتوى عربي")),
        language_code="ar",
    )

    assert chunks[0].language_code == "ar"
    assert chunks[0].metadata["strategy"] == ChunkingStrategy.FIXED_TOKEN_V1.value


@pytest.mark.parametrize(
    ("max_tokens", "overlap_tokens"),
    [(0, 0), (10, 10), (10, 11), (10, -1)],
)
def test_invalid_token_bounds_are_rejected(max_tokens: int, overlap_tokens: int) -> None:
    with pytest.raises(ValueError):
        FixedTokenChunker(max_tokens=max_tokens, overlap_tokens=overlap_tokens)
