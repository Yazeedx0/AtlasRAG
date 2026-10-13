import json
import shutil
from pathlib import Path

import pytest
from atlasrag.contracts.types.extraction import ExtractedBlockType

from evals.core.errors import DatasetIntegrityError, FixtureManifestError
from evals.core.language import EvalLanguage
from evals.datasets.contract import FixtureSourceType
from evals.datasets.loader import FIXTURES_ROOT, MANIFEST_NAME, load_dataset

EXPECTED_FIXTURE_IDS = (
    "en_prose_handbook",
    "ar_prose_leave_policy",
    "en_nested_headings_security",
    "ar_table_financials",
    "en_long_section_architecture",
    "ar_long_section_procurement",
)


@pytest.fixture
def fixtures_copy(tmp_path: Path) -> Path:
    destination = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_ROOT, destination)
    return destination


def _write_manifest(root: Path, payload: dict[str, object]) -> None:
    (root / MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")


def test_dataset_loads_every_fixture_in_manifest_order() -> None:
    dataset = load_dataset()

    assert tuple(fixture.fixture_id for fixture in dataset.fixtures) == EXPECTED_FIXTURE_IDS


def test_dataset_loading_is_deterministic() -> None:
    first = load_dataset()
    second = load_dataset()

    assert first == second
    assert first.content_hash == second.content_hash


def test_fixture_content_hashes_are_unique_per_fixture() -> None:
    hashes = [fixture.content_hash for fixture in load_dataset().fixtures]

    assert len(set(hashes)) == len(hashes)


def test_dataset_hash_changes_when_fixture_content_changes(fixtures_copy: Path) -> None:
    baseline = load_dataset(root=fixtures_copy)
    target = fixtures_copy / "en_prose_handbook.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["blocks"][1]["text"] = payload["blocks"][1]["text"] + " Amended."
    target.write_text(json.dumps(payload), encoding="utf-8")

    assert load_dataset(root=fixtures_copy).content_hash != baseline.content_hash


def test_dataset_hash_changes_when_manifest_order_changes(fixtures_copy: Path) -> None:
    baseline = load_dataset(root=fixtures_copy)
    manifest = json.loads((fixtures_copy / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["fixtures"] = list(reversed(manifest["fixtures"]))
    _write_manifest(fixtures_copy, manifest)

    assert load_dataset(root=fixtures_copy).content_hash != baseline.content_hash


def test_languages_are_declared_on_every_fixture() -> None:
    languages = {fixture.language for fixture in load_dataset().fixtures}

    assert languages == {EvalLanguage.ENGLISH, EvalLanguage.ARABIC}


def test_both_languages_are_represented_by_more_than_one_fixture() -> None:
    dataset = load_dataset()

    assert len(dataset.by_language(EvalLanguage.ENGLISH)) >= 2
    assert len(dataset.by_language(EvalLanguage.ARABIC)) >= 2


def test_every_declared_source_type_is_covered() -> None:
    covered = {fixture.source_type for fixture in load_dataset().fixtures}

    assert covered == set(FixtureSourceType)


def test_table_fixture_carries_table_blocks() -> None:
    fixture = next(
        item for item in load_dataset().fixtures if item.fixture_id == "ar_table_financials"
    )
    tables = [
        block
        for block in fixture.document.blocks
        if block.block_type is ExtractedBlockType.TABLE
    ]

    assert len(tables) == fixture.expected_structure.table_count == 2


def test_nested_heading_fixture_declares_multiple_heading_levels() -> None:
    fixture = next(
        item
        for item in load_dataset().fixtures
        if item.fixture_id == "en_nested_headings_security"
    )
    levels = {
        block.metadata["level"]
        for block in fixture.document.blocks
        if block.block_type is ExtractedBlockType.HEADING
    }

    assert levels == {1, 2, 3}


def test_annotated_boundaries_reference_real_blocks() -> None:
    for fixture in load_dataset().fixtures:
        for boundary in fixture.annotated_boundaries:
            assert 0 <= boundary.after_block_index < len(fixture.document.blocks)
            assert boundary.rationale


def test_loader_rejects_a_fixture_whose_declared_structure_is_wrong(
    fixtures_copy: Path,
) -> None:
    target = fixtures_copy / "en_prose_handbook.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["expected_structure"]["heading_count"] = 99
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetIntegrityError):
        load_dataset(root=fixtures_copy)


def test_loader_rejects_declared_pages_that_do_not_match_the_blocks(
    fixtures_copy: Path,
) -> None:
    target = fixtures_copy / "ar_prose_leave_policy.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["expected_structure"]["pages_covered"] = [1]
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetIntegrityError):
        load_dataset(root=fixtures_copy)


def test_loader_rejects_an_unsupported_manifest_schema(fixtures_copy: Path) -> None:
    manifest = json.loads((fixtures_copy / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["schema_version"] = "99"
    _write_manifest(fixtures_copy, manifest)

    with pytest.raises(FixtureManifestError):
        load_dataset(root=fixtures_copy)


def test_loader_rejects_a_manifest_listing_the_same_fixture_twice(fixtures_copy: Path) -> None:
    manifest = json.loads((fixtures_copy / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["fixtures"] = [*manifest["fixtures"], manifest["fixtures"][0]]
    _write_manifest(fixtures_copy, manifest)

    with pytest.raises(FixtureManifestError):
        load_dataset(root=fixtures_copy)


def test_loader_rejects_a_manifest_pointing_at_a_missing_file(fixtures_copy: Path) -> None:
    manifest = json.loads((fixtures_copy / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["fixtures"] = [*manifest["fixtures"], "not_written_yet.json"]
    _write_manifest(fixtures_copy, manifest)

    with pytest.raises(FixtureManifestError):
        load_dataset(root=fixtures_copy)


def test_fixture_block_metadata_is_immutable() -> None:
    block = load_dataset().fixtures[0].document.blocks[0]

    with pytest.raises(TypeError):
        block.metadata["level"] = 9
