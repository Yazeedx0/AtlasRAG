import pytest

from evals.core.errors import UnknownTokenizerError
from evals.core.tokenization import (
    CL100K_TOKENIZER,
    UNICODE_WORD_TOKENIZER,
    Tokenizer,
    UnicodeWordTokenizer,
    create_tokenizer,
)


def test_unicode_word_tokenizer_satisfies_the_protocol() -> None:
    assert isinstance(UnicodeWordTokenizer(), Tokenizer)


def test_unicode_word_tokenizer_counts_english_words() -> None:
    assert UnicodeWordTokenizer().count("the quick brown fox") == 4


def test_unicode_word_tokenizer_counts_arabic_words() -> None:
    assert UnicodeWordTokenizer().count("يستحق الموظف إجازة سنوية") == 4


def test_unicode_word_tokenizer_separates_punctuation_from_words() -> None:
    assert UnicodeWordTokenizer().tokenize("14 days, paid.") == ("14", "days", ",", "paid", ".")


def test_unicode_word_tokenizer_is_stable_across_instances() -> None:
    text = "سبعون يوماً paid leave, 70 days."

    assert UnicodeWordTokenizer().tokenize(text) == UnicodeWordTokenizer().tokenize(text)


def test_unicode_word_tokenizer_identity_is_recorded_for_reproducibility() -> None:
    identity = UnicodeWordTokenizer().identity

    assert (identity.name, identity.version, identity.encoding) == ("unicode-word", "1", None)


def test_detokenize_round_trips_token_counts() -> None:
    tokenizer = UnicodeWordTokenizer()
    tokens = tokenizer.tokenize("الإجازة السنوية annual leave")

    assert tokenizer.count(tokenizer.detokenize(tokens)) == len(tokens)


def test_create_tokenizer_resolves_the_registered_default() -> None:
    assert isinstance(create_tokenizer(UNICODE_WORD_TOKENIZER), UnicodeWordTokenizer)


def test_create_tokenizer_rejects_an_unregistered_name() -> None:
    with pytest.raises(UnknownTokenizerError):
        create_tokenizer("word-count")


def test_tiktoken_tokenizer_reports_its_encoding_when_available() -> None:
    pytest.importorskip("tiktoken")
    identity = create_tokenizer(CL100K_TOKENIZER).identity

    assert identity.name == "tiktoken"
    assert identity.encoding == CL100K_TOKENIZER
    assert identity.version
