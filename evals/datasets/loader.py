import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from atlasrag.contracts.types.extraction import (
    ExtractedBlock,
    ExtractedBlockType,
    ExtractedDocument,
)

from evals.core._hashing import hash_payload
from evals.core.errors import DatasetIntegrityError, FixtureManifestError
from evals.core.language import EvalLanguage
from evals.datasets.contract import (
    FIXTURE_SCHEMA_VERSION,
    AnnotatedBoundary,
    EvalDataset,
    EvalFixture,
    ExpectedStructure,
    FixtureSourceType,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures"
MANIFEST_NAME = "manifest.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FixtureManifestError(f"missing fixture file: {path}")
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FixtureManifestError(f"fixture file is not a JSON object: {path}")
    return payload


def _parse_block(payload: dict[str, Any], *, fixture_id: str, index: int) -> ExtractedBlock:
    block_type = payload["block_type"]
    if block_type not in set(ExtractedBlockType):
        raise DatasetIntegrityError(
            f"{fixture_id}: block {index} has unknown block_type {block_type!r}"
        )
    metadata: dict[str, object] = dict(payload.get("metadata", {}))
    return ExtractedBlock(
        text=payload["text"],
        block_type=ExtractedBlockType(block_type),
        page_number=payload.get("page_number"),
        metadata=MappingProxyType(metadata),
    )


def _parse_expected_structure(payload: dict[str, Any]) -> ExpectedStructure:
    return ExpectedStructure(
        heading_count=payload["heading_count"],
        table_count=payload["table_count"],
        requires_splitting=payload["requires_splitting"],
        pages_covered=tuple(payload["pages_covered"]),
    )


def _verify_expected_structure(
    *, fixture_id: str, document: ExtractedDocument, expected: ExpectedStructure
) -> None:
    headings = sum(
        1 for block in document.blocks if block.block_type is ExtractedBlockType.HEADING
    )
    tables = sum(1 for block in document.blocks if block.block_type is ExtractedBlockType.TABLE)
    pages = tuple(
        sorted({block.page_number for block in document.blocks if block.page_number is not None})
    )
    if headings != expected.heading_count:
        raise DatasetIntegrityError(
            f"{fixture_id}: declared {expected.heading_count} headings, document has {headings}"
        )
    if tables != expected.table_count:
        raise DatasetIntegrityError(
            f"{fixture_id}: declared {expected.table_count} tables, document has {tables}"
        )
    if pages != expected.pages_covered:
        raise DatasetIntegrityError(
            f"{fixture_id}: declared pages {expected.pages_covered}, document has {pages}"
        )


def _parse_fixture(payload: dict[str, Any], *, path: Path) -> EvalFixture:
    schema_version = payload.get("schema_version")
    if schema_version != FIXTURE_SCHEMA_VERSION:
        raise FixtureManifestError(
            f"{path.name}: fixture schema_version {schema_version!r} is not supported"
        )
    fixture_id = payload["fixture_id"]
    blocks = tuple(
        _parse_block(block, fixture_id=fixture_id, index=index)
        for index, block in enumerate(payload["blocks"])
    )
    document = ExtractedDocument(
        blocks=blocks,
        metadata=MappingProxyType(dict(payload.get("document_metadata", {}))),
    )
    expected_structure = _parse_expected_structure(payload["expected_structure"])
    _verify_expected_structure(
        fixture_id=fixture_id, document=document, expected=expected_structure
    )
    boundaries = tuple(
        AnnotatedBoundary(
            after_block_index=entry["after_block_index"], rationale=entry["rationale"]
        )
        for entry in payload.get("annotated_boundaries", [])
    )
    return EvalFixture(
        fixture_id=fixture_id,
        title=payload["title"],
        language=EvalLanguage(payload["language"]),
        source_type=FixtureSourceType(payload["source_type"]),
        document=document,
        expected_structure=expected_structure,
        annotated_boundaries=boundaries,
        content_hash=hash_payload(payload),
    )


def load_dataset(*, root: Path = FIXTURES_ROOT) -> EvalDataset:
    manifest = _read_json(root / MANIFEST_NAME)
    if manifest.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise FixtureManifestError("manifest schema_version is not supported")

    fixture_names: list[str] = list(manifest["fixtures"])
    if len(set(fixture_names)) != len(fixture_names):
        raise FixtureManifestError("manifest lists a fixture file more than once")

    fixtures = tuple(
        _parse_fixture(_read_json(root / name), path=root / name) for name in fixture_names
    )
    fixture_ids = [fixture.fixture_id for fixture in fixtures]
    if len(set(fixture_ids)) != len(fixture_ids):
        raise DatasetIntegrityError("manifest resolves to duplicate fixture ids")

    dataset_id = manifest["dataset_id"]
    version = manifest["version"]
    content_hash = hash_payload(
        {
            "dataset_id": dataset_id,
            "version": version,
            "fixtures": [
                {"fixture_id": fixture.fixture_id, "content_hash": fixture.content_hash}
                for fixture in fixtures
            ],
        }
    )
    return EvalDataset(
        dataset_id=dataset_id,
        version=version,
        fixtures=fixtures,
        content_hash=content_hash,
    )


__all__ = ["FIXTURES_ROOT", "MANIFEST_NAME", "load_dataset"]
