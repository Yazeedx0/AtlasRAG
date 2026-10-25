import dataclasses

import pytest

from atlasrag.contracts.chunking import Chunker, ReferenceTokenizer
from atlasrag.contracts.types.chunking import ChunkContentType, ChunkDraft
from atlasrag.contracts.types.extraction import ExtractedDocument

pytestmark = pytest.mark.unit


def make_draft() -> ChunkDraft:
    return ChunkDraft(
        chunk_index=0,
        content="Employees receive annual leave.",
        content_type=ChunkContentType.TEXT,
        section_title="Leave",
        section_path=("Employee Handbook", "Benefits", "Leave"),
        page_start=12,
        page_end=13,
        language_code="en",
        token_count=5,
        content_hash="a" * 64,
    )


def test_chunk_draft_is_immutable() -> None:
    draft = make_draft()

    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.content = "changed"


def test_chunk_draft_metadata_default_cannot_be_mutated() -> None:
    draft = make_draft()

    with pytest.raises(TypeError):
        draft.metadata["injected"] = True


def test_chunk_content_type_values_are_stable() -> None:
    assert {content_type.value for content_type in ChunkContentType} == {
        "text",
        "table",
        "code",
        "mixed",
    }


def test_fake_chunker_satisfies_contract_without_persistence() -> None:
    class FakeChunker:
        def chunk(
            self,
            *,
            document: ExtractedDocument,
            language_code: str | None = None,
        ) -> tuple[ChunkDraft, ...]:
            assert document.blocks == ()
            assert language_code == "en"
            return (make_draft(),)

    chunker: Chunker = FakeChunker()

    assert isinstance(chunker, Chunker)
    assert chunker.chunk(document=ExtractedDocument(blocks=()), language_code="en") == (
        make_draft(),
    )


def test_fake_reference_tokenizer_satisfies_contract_without_persistence() -> None:
    class FakeReferenceTokenizer:
        def count(self, *, text: str) -> int:
            return len(text.split())

        def split(
            self,
            *,
            text: str,
            max_tokens: int,
            overlap_tokens: int,
        ) -> tuple[str, ...]:
            assert overlap_tokens == 0
            words = text.split()
            return tuple(
                " ".join(words[index : index + max_tokens])
                for index in range(0, len(words), max_tokens)
            )

    tokenizer: ReferenceTokenizer = FakeReferenceTokenizer()

    assert isinstance(tokenizer, ReferenceTokenizer)
    assert tokenizer.count(text="one two three") == 3
    assert tokenizer.split(text="one two three", max_tokens=2, overlap_tokens=0) == (
        "one two",
        "three",
    )
