from datetime import timedelta

import pytest

from atlasrag.platform.jobs.backoff import ExponentialBackoff


def make_backoff() -> ExponentialBackoff:
    return ExponentialBackoff(base=timedelta(seconds=5), maximum=timedelta(minutes=10))


def test_delay_doubles_with_each_attempt() -> None:
    backoff = make_backoff()

    assert backoff.delay_for(attempt_number=1) == timedelta(seconds=5)
    assert backoff.delay_for(attempt_number=2) == timedelta(seconds=10)
    assert backoff.delay_for(attempt_number=3) == timedelta(seconds=20)


def test_delay_is_capped_at_the_maximum() -> None:
    backoff = make_backoff()

    assert backoff.delay_for(attempt_number=20) == timedelta(minutes=10)
    assert backoff.delay_for(attempt_number=10_000) == timedelta(minutes=10)


def test_attempt_number_below_one_is_rejected() -> None:
    backoff = make_backoff()

    with pytest.raises(ValueError, match="Attempt number"):
        backoff.delay_for(attempt_number=0)


def test_non_positive_base_is_rejected() -> None:
    with pytest.raises(ValueError, match="Backoff base"):
        ExponentialBackoff(base=timedelta(0), maximum=timedelta(minutes=1))


def test_maximum_below_base_is_rejected() -> None:
    with pytest.raises(ValueError, match="Backoff maximum"):
        ExponentialBackoff(base=timedelta(seconds=30), maximum=timedelta(seconds=5))
