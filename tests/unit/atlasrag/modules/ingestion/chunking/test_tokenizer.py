import pytest

from atlasrag.modules.ingestion.chunking.tokenizer import ReferenceTextTokenizer

ARABIC_PARAGRAPH = "الذكاء الاصطناعي يغير طريقة عمل المؤسسات"
ENGLISH_PARAGRAPH = "Retrieval augmented generation, done carefully."


@pytest.mark.parametrize(
    "text",
    [
        ENGLISH_PARAGRAPH,
        ARABIC_PARAGRAPH,
        "  leading and trailing whitespace  ",
        "line one\n\nline two",
        "| a | b |\n|---|---|\n| 1 | 2 |",
    ],
)
def test_split_tokens_is_lossless(text: str) -> None:
    tokenizer = ReferenceTextTokenizer()

    assert "".join(tokenizer.split_tokens(text)) == text


@pytest.mark.parametrize("text", [ENGLISH_PARAGRAPH, ARABIC_PARAGRAPH])
def test_count_tokens_matches_split_length(text: str) -> None:
    tokenizer = ReferenceTextTokenizer()

    assert tokenizer.count_tokens(text) == len(tokenizer.split_tokens(text))


def test_split_tokens_is_deterministic() -> None:
    tokenizer = ReferenceTextTokenizer()

    assert tokenizer.split_tokens(ARABIC_PARAGRAPH) == tokenizer.split_tokens(
        ARABIC_PARAGRAPH
    )


def test_blank_text_has_no_tokens() -> None:
    tokenizer = ReferenceTextTokenizer()

    assert tokenizer.split_tokens("   \n  ") == ()
    assert tokenizer.count_tokens("") == 0


def test_long_words_are_split_into_bounded_tokens() -> None:
    tokenizer = ReferenceTextTokenizer(characters_per_token=4)

    tokens = tokenizer.split_tokens("supercalifragilistic")

    assert len(tokens) == 5
    assert all(len(token.strip()) <= 4 for token in tokens)


def test_punctuation_counts_as_its_own_token() -> None:
    tokenizer = ReferenceTextTokenizer()

    assert tokenizer.count_tokens("a, b") == 3


def test_characters_per_token_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ReferenceTextTokenizer(characters_per_token=0)
