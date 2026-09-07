import json
import uuid

import pytest
import structlog

from atlasrag.contracts.types.observability import JobStage, SpanName
from atlasrag.platform.observability import (
    DROPPED,
    REDACTED,
    ingestion_job_context,
    redact_event,
    scrub_text,
    traced_stage_sync,
)

pytestmark = pytest.mark.unit

_ARABIC_DOCUMENT_TEXT = "هذه وثيقة سرية تخص الموارد البشرية"
_JWT = (
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkF0bGFzIn0"
    ".dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
)
_REDIS_URL = "redis://atlas:sup3rs3cret@redis.internal:6379/0"
_POSTGRES_URL = "postgresql+asyncpg://atlas:hunter2@db.internal:5432/atlasrag"


def _render(**fields: object) -> dict[str, object]:
    return dict(redact_event(None, "info", {"event": "ingestion_job_started", **fields}))


def test_document_content_is_never_logged() -> None:
    rendered = _render(
        document_text=_ARABIC_DOCUMENT_TEXT,
        extracted_text="Confidential salary bands",
        content=b"%PDF-1.7 binary",
    )

    assert rendered["document_text"] == DROPPED
    assert rendered["extracted_text"] == DROPPED
    assert rendered["content"] == DROPPED
    assert _ARABIC_DOCUMENT_TEXT not in json.dumps(rendered, ensure_ascii=False)


def test_credentials_and_tokens_are_redacted() -> None:
    rendered = _render(
        api_key="sk-live-0123456789abcdef",
        password="hunter2",
        authorization=f"Bearer {_JWT}",
        minio_secret_key="s3cret",
    )

    assert rendered["api_key"] == REDACTED
    assert rendered["password"] == REDACTED
    assert rendered["authorization"] == REDACTED
    assert rendered["minio_secret_key"] == REDACTED
    assert "hunter2" not in json.dumps(rendered)


def test_broker_and_database_urls_are_redacted() -> None:
    rendered = _render(redis_url=_REDIS_URL, database_url=_POSTGRES_URL)

    assert rendered["redis_url"] == REDACTED
    assert rendered["database_url"] == REDACTED
    assert "sup3rs3cret" not in json.dumps(rendered)
    assert "hunter2" not in json.dumps(rendered)


def test_credentials_embedded_in_free_text_are_scrubbed() -> None:
    scrubbed = scrub_text(f"failed to reach {_REDIS_URL}")

    assert "sup3rs3cret" not in scrubbed
    assert REDACTED in scrubbed


def test_bare_jwt_in_free_text_is_scrubbed() -> None:
    scrubbed = scrub_text(f"token was {_JWT} for the request")

    assert _JWT not in scrubbed
    assert REDACTED in scrubbed


def test_nested_structures_are_scrubbed() -> None:
    rendered = _render(
        execution_metadata={
            "extraction": {"method": "openai_ocr", "api_key": "sk-live-abcdef012345"},
            "blocks": [_ARABIC_DOCUMENT_TEXT],
        }
    )

    serialized = json.dumps(rendered, ensure_ascii=False)

    assert "sk-live-abcdef012345" not in serialized
    assert _ARABIC_DOCUMENT_TEXT not in serialized
    assert "openai_ocr" in serialized


def test_long_strings_are_truncated() -> None:
    rendered = _render(note="x" * 5000)
    note = rendered["note"]

    assert isinstance(note, str)
    assert len(note) < 600


def test_job_context_binds_identifiers_for_logs_without_content(
    observability: object,
) -> None:
    _ = observability
    item_id = uuid.uuid4()
    run_id = uuid.uuid4()
    artifact_id = uuid.uuid4()

    with (
        ingestion_job_context(
            job_type="ingestion.process",
            ingestion_item_id=item_id,
            ingestion_run_id=run_id,
            artifact_id=artifact_id,
            attempt_number=2,
            language_code="ar",
        ),
        traced_stage_sync(SpanName.EXTRACTION, stage=JobStage.EXTRACTION),
    ):
        bound = structlog.contextvars.get_contextvars()

    assert bound["ingestion_item_id"] == str(item_id)
    assert bound["ingestion_run_id"] == str(run_id)
    assert bound["artifact_id"] == str(artifact_id)
    assert bound["attempt_number"] == 2
    assert bound["job_type"] == "ingestion.process"
    assert bound["language"] == "ar"
    assert bound["stage"] == JobStage.EXTRACTION.value


def test_job_context_is_unbound_after_the_job_ends() -> None:
    with ingestion_job_context(job_type="ingestion.process"):
        pass

    assert "ingestion_item_id" not in structlog.contextvars.get_contextvars()
    assert "job_type" not in structlog.contextvars.get_contextvars()


def test_span_attributes_refuse_sensitive_and_content_keys(observability: object) -> None:
    _ = observability
    with traced_stage_sync(SpanName.EXTRACTION) as observation:
        observation.set_attribute("document_text", _ARABIC_DOCUMENT_TEXT)
        observation.set_attribute("api_key", "sk-live-0123456789")
        observation.set_attribute("block_count", 12)

    span = observation.span
    assert span is not None
    attributes = span.attributes  # type: ignore[attr-defined]
    assert "document_text" not in attributes
    assert "api_key" not in attributes
    assert attributes["block_count"] == 12
