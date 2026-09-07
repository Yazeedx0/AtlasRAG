import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import structlog

from atlasrag.contracts.types.observability import JobStage, LanguageLabel
from atlasrag.platform.observability._cardinality import normalize_language


@dataclass
class IngestionJobContext:
    job_type: str
    ingestion_item_id: uuid.UUID | None = None
    ingestion_run_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    attempt_number: int | None = None
    language: LanguageLabel = LanguageLabel.UNKNOWN
    failed_stage: JobStage | None = None


_JOB_CONTEXT: ContextVar[IngestionJobContext | None] = ContextVar(
    "atlasrag_ingestion_job_context",
    default=None,
)

_STAGE: ContextVar[JobStage] = ContextVar(
    "atlasrag_ingestion_stage",
    default=JobStage.UNKNOWN,
)

_UNKNOWN_JOB_TYPE = "unknown"


def current_job_context() -> IngestionJobContext | None:
    return _JOB_CONTEXT.get()


def current_language() -> LanguageLabel:
    context = _JOB_CONTEXT.get()
    return LanguageLabel.UNKNOWN if context is None else context.language


def current_job_type() -> str:
    context = _JOB_CONTEXT.get()
    return _UNKNOWN_JOB_TYPE if context is None else context.job_type


def current_stage() -> JobStage:
    return _STAGE.get()


def failed_stage() -> JobStage:
    context = _JOB_CONTEXT.get()
    if context is None or context.failed_stage is None:
        return JobStage.UNKNOWN
    return context.failed_stage


def mark_stage_failure(stage: JobStage) -> None:
    context = _JOB_CONTEXT.get()
    if context is not None and context.failed_stage is None:
        context.failed_stage = stage
    return None


def _log_fields(context: IngestionJobContext) -> dict[str, object]:
    fields: dict[str, object] = {
        "job_type": context.job_type,
        "language": context.language.value,
    }
    if context.ingestion_item_id is not None:
        fields["ingestion_item_id"] = str(context.ingestion_item_id)
    if context.ingestion_run_id is not None:
        fields["ingestion_run_id"] = str(context.ingestion_run_id)
    if context.artifact_id is not None:
        fields["artifact_id"] = str(context.artifact_id)
    if context.attempt_number is not None:
        fields["attempt_number"] = context.attempt_number
    return fields


@contextmanager
def ingestion_job_context(
    *,
    job_type: str,
    ingestion_item_id: uuid.UUID | None = None,
    ingestion_run_id: uuid.UUID | None = None,
    artifact_id: uuid.UUID | None = None,
    attempt_number: int | None = None,
    language_code: str | None = None,
) -> Iterator[IngestionJobContext]:
    context = IngestionJobContext(
        job_type=job_type,
        ingestion_item_id=ingestion_item_id,
        ingestion_run_id=ingestion_run_id,
        artifact_id=artifact_id,
        attempt_number=attempt_number,
        language=normalize_language(language_code),
    )
    token = _JOB_CONTEXT.set(context)
    structlog.contextvars.bind_contextvars(stage=JobStage.UNKNOWN.value, **_log_fields(context))
    try:
        yield context
    finally:
        _JOB_CONTEXT.reset(token)
        structlog.contextvars.unbind_contextvars(
            "job_type",
            "language",
            "stage",
            "ingestion_item_id",
            "ingestion_run_id",
            "artifact_id",
            "attempt_number",
        )


def sync_log_context() -> None:
    context = _JOB_CONTEXT.get()
    if context is not None:
        structlog.contextvars.bind_contextvars(**_log_fields(context))
    return None


def update_job_context(
    *,
    ingestion_item_id: uuid.UUID | None = None,
    ingestion_run_id: uuid.UUID | None = None,
    artifact_id: uuid.UUID | None = None,
    attempt_number: int | None = None,
    language_code: str | None = None,
) -> None:
    context = _JOB_CONTEXT.get()
    if context is None:
        return None

    if ingestion_item_id is not None:
        context.ingestion_item_id = ingestion_item_id
    if ingestion_run_id is not None:
        context.ingestion_run_id = ingestion_run_id
    if artifact_id is not None:
        context.artifact_id = artifact_id
    if attempt_number is not None:
        context.attempt_number = attempt_number
    if language_code is not None:
        context.language = normalize_language(language_code)
    structlog.contextvars.bind_contextvars(**_log_fields(context))
    return None


@contextmanager
def job_stage(stage: JobStage) -> Iterator[None]:
    previous = _STAGE.get()
    token = _STAGE.set(stage)
    structlog.contextvars.bind_contextvars(stage=stage.value)
    try:
        yield None
    except BaseException:
        mark_stage_failure(stage)
        raise
    finally:
        _STAGE.reset(token)
        structlog.contextvars.bind_contextvars(stage=previous.value)


__all__ = [
    "IngestionJobContext",
    "current_job_context",
    "current_job_type",
    "current_language",
    "current_stage",
    "failed_stage",
    "ingestion_job_context",
    "job_stage",
    "mark_stage_failure",
    "sync_log_context",
    "update_job_context",
]
