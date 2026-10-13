from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from typing import Any

from evals.core._hashing import canonical_json, hash_payload

REPORT_SCHEMA_VERSION = "1"
EVALUATION_FRAMEWORK_VERSION = "0.1.0"


class MetricKind(StrEnum):
    OBJECTIVE = "objective"
    HEURISTIC = "heuristic"


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    dataset_id: str
    version: str
    content_hash: str
    fixture_count: int


@dataclass(frozen=True, slots=True)
class RunProvenance:
    framework_version: str = EVALUATION_FRAMEWORK_VERSION
    generated_at: str | None = None
    git_commit: str | None = None
    run_label: str | None = None


def to_serializable(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_serializable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): to_serializable(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, str | bool | int | float) or value is None:
        return value
    if isinstance(value, Sequence):
        return [to_serializable(item) for item in value]
    return value


def fingerprint(value: object) -> str:
    return hash_payload(to_serializable(value))


def dump_report(report: object) -> str:
    return canonical_json(to_serializable(report))


__all__ = [
    "EVALUATION_FRAMEWORK_VERSION",
    "REPORT_SCHEMA_VERSION",
    "DatasetIdentity",
    "MetricKind",
    "RunProvenance",
    "dump_report",
    "fingerprint",
    "to_serializable",
]
