from enum import StrEnum


class EvalLanguage(StrEnum):
    ENGLISH = "en"
    ARABIC = "ar"
    MIXED = "mixed"


class MetricSubset(StrEnum):
    OVERALL = "overall"
    ENGLISH = "en"
    ARABIC = "ar"


REPORTED_SUBSETS: tuple[MetricSubset, ...] = (
    MetricSubset.OVERALL,
    MetricSubset.ENGLISH,
    MetricSubset.ARABIC,
)


def subset_accepts(subset: MetricSubset, language: EvalLanguage) -> bool:
    if subset is MetricSubset.OVERALL:
        return True
    if subset is MetricSubset.ENGLISH:
        return language is EvalLanguage.ENGLISH
    return language is EvalLanguage.ARABIC


__all__ = ["REPORTED_SUBSETS", "EvalLanguage", "MetricSubset", "subset_accepts"]
