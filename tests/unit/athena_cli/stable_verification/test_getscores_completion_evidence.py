from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresBranchCase,
    GetscoresCompletionEvidence,
    GetscoresEvidenceSource,
    GetscoresEvidenceStatus,
    GetscoresEvidenceValidationError,
    GetscoresIdentityProfile,
    GetscoresMutationProfile,
    GetscoresRequestSelector,
    GetscoresSeedProfile,
    GetscoresWireShapeId,
    load_getscores_completion_evidence,
    validate_getscores_completion_evidence,
)
from athena_cli.stable_verification.models import StableSurface, VerificationStatus

if TYPE_CHECKING:
    from pathlib import Path


def test_load_getscores_completion_evidence_returns_immutable_typed_bundle(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    assert isinstance(evidence, GetscoresCompletionEvidence)
    assert isinstance(evidence.response_shapes, tuple)
    assert isinstance(evidence.branch_cases, tuple)
    assert isinstance(evidence.status_crosswalk, tuple)
    assert evidence.response_shapes[0].shape_id is GetscoresWireShapeId.AUTH_FAILURE
    assert evidence.branch_cases[0].expected_shape_id is GetscoresWireShapeId.AUTH_FAILURE
    assert evidence.branch_cases[0].evidence_status is GetscoresEvidenceStatus.CONFIRMED
    assert evidence.branch_cases[0].mutation_profiles == (
        GetscoresMutationProfile.REQUEST_VERSION_VARIANT,
    )
    results = validate_getscores_completion_evidence(evidence)
    assert len(results) == 3
    assert {result.surface for result in results} == {StableSurface.GETSCORES}
    assert {result.status for result in results} == {VerificationStatus.PASS}


def test_manifest_rejects_unknown_schema_and_top_level_fields_without_echoing_value(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    document["schema"] = "secret-schema-value"
    document["unexpected"] = "raw-secret-value"
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "response_shapes.json" in message
    assert "unknown_schema" in message
    assert "unknown_top_level_field" in message
    assert "secret-schema-value" not in message
    assert "raw-secret-value" not in message


def test_manifest_missing_file_reports_safe_validation_error(tmp_path: Path) -> None:
    manifest_root = tmp_path / "manifests"
    body_root = tmp_path / "bodies"
    manifest_root.mkdir()
    body_root.mkdir()

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "missing_manifest" in message
    assert str(tmp_path) not in message


def test_manifest_rejects_duplicate_ids_deterministically(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    shapes = _entries(document, "shapes")
    duplicate = dict(shapes[0])
    shapes.append(duplicate)
    document["shapes"] = shapes
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    assert "duplicate_id" in str(raised.value)
    assert "auth_failure" not in str(raised.value)


def test_manifest_rejects_unknown_shape_reference(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    _entries(document, "cases")[0]["expected_shape_id"] = "not-a-shape"
    _write_document(branch_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    assert "unknown_shape_id" in str(raised.value)
    assert "not-a-shape" not in str(raised.value)


def test_manifest_rejects_valid_but_unregistered_shape_reference(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    _entries(document, "cases")[0]["expected_shape_id"] = "header_only"
    _write_document(branch_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "unknown_shape_id" in message
    assert "header_only" not in message


def test_manifest_rejects_fixture_root_escape(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    _entries(document, "shapes")[0]["body_file"] = "../outside.body"
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "unsafe_body_path" in message
    assert "outside.body" not in message


def test_manifest_rejects_missing_body_file_without_echoing_path(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    _entries(document, "shapes")[0]["body_file"] = "missing-secret-body.body"
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "missing_body_file" in message
    assert "missing-secret-body.body" not in message


def test_manifest_rejects_non_object_collection_entry(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    raw_entries = cast("list[object]", document["shapes"])
    raw_entries.append("raw-entry-value")
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "entry_must_be_object" in message
    assert "raw-entry-value" not in message


def test_manifest_rejects_raw_secret_and_query_fields_without_echoing_values(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    case_entry = _entries(document, "cases")[0]
    case_entry["raw_query"] = "c=raw-secret-value"
    case_entry["credential"] = "password-value"
    _write_document(branch_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "forbidden_raw_query_field" in message
    assert "forbidden_credential_field" in message
    assert "raw-secret-value" not in message
    assert "password-value" not in message


def test_public_branch_case_model_is_frozen_and_slotted() -> None:
    case = GetscoresBranchCase(
        case_id="case",
        identity_profile=GetscoresIdentityProfile.AUTH_MISSING,
        request_selector=GetscoresRequestSelector.GLOBAL_DOMAIN,
        expected_domain_category=None,
        seed_profile=GetscoresSeedProfile.NONE,
        mutation_profiles=(),
        expected_shape_id=GetscoresWireShapeId.AUTH_FAILURE,
        expected_warning_categories=(),
        evidence_status=GetscoresEvidenceStatus.CONFIRMED,
    )

    assert hasattr(case, "__slots__")
    changed = replace(case, case_id="changed")
    assert case.case_id == "case"
    assert changed.case_id == "changed"


def test_manifest_rejects_wrong_top_level_collection_type(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    document["shapes"] = {"shape_id": "auth_failure"}
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    assert "collection_must_be_list" in str(raised.value)


def test_manifest_rejects_raw_username_field(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    _entries(document, "cases")[0]["raw_username"] = "hidden-user"
    _write_document(branch_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "forbidden_username_field" in message
    assert "hidden-user" not in message


def test_manifest_rejects_non_utf8_bytes_without_echoing_content(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    _ = response_path.write_bytes(b"{\xff")

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "invalid_utf8" in message
    assert "\\xff" not in message


def test_manifest_root_resolution_failure_is_safe(tmp_path: Path) -> None:
    manifest_root = tmp_path / "manifest-loop"
    body_root = tmp_path / "bodies"
    manifest_root.symlink_to(manifest_root)
    body_root.mkdir()

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "unsafe_root_path" in message
    assert str(tmp_path) not in message


def test_evidence_source_is_typed_and_rejects_raw_query_like_reference(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    crosswalk_path = manifest_root / "beatmap_status_crosswalk.json"
    document = _read_document(crosswalk_path)
    entries = cast("list[object]", document["entries"])
    entries.append(
        {
            "canonical_status": "ranked",
            "getscores": {
                "representation": "wire",
                "wire_status": 2,
                "evidence_status": "confirmed",
                "evidence_sources": ["official_fixture:ranked"],
            },
            "beatmap_info": {
                "representation": "unconfirmed",
                "wire_status": None,
                "evidence_status": "unconfirmed",
                "evidence_sources": [],
            },
        }
    )
    _write_document(crosswalk_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    source = evidence.status_crosswalk[0].getscores.evidence_sources[0]
    assert isinstance(source, GetscoresEvidenceSource)
    assert source == "official_fixture:ranked"

    entry = cast("dict[str, object]", entries[0])
    entry["getscores"] = {
        "representation": "wire",
        "wire_status": 2,
        "evidence_status": "confirmed",
        "evidence_sources": ["u=raw-secret"],
    }
    _write_document(crosswalk_path, document)
    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "invalid_evidence_source" in message
    assert "u=raw-secret" not in message


def test_wire_status_representation_requires_numeric_status(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    crosswalk_path = manifest_root / "beatmap_status_crosswalk.json"
    document = _read_document(crosswalk_path)
    document["entries"] = [
        _crosswalk_entry(
            getscores_representation="wire",
            getscores_wire_status=None,
            getscores_sources=("official_fixture:ranked",),
        )
    ]
    _write_document(crosswalk_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    assert "wire_status_required" in str(raised.value)


def test_evidence_source_rejects_parent_path_segments(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    crosswalk_path = manifest_root / "beatmap_status_crosswalk.json"
    document = _read_document(crosswalk_path)
    document["entries"] = [
        _crosswalk_entry(
            getscores_representation="wire",
            getscores_wire_status=2,
            getscores_sources=("docs:fixtures/../../private",),
        )
    ]
    _write_document(crosswalk_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "invalid_evidence_source" in message
    assert "private" not in message


def test_manifest_rejects_excessive_nesting_deterministically(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    nested: object = None
    for _ in range(80):
        nested = {"safe": nested}
    document["metadata"] = nested
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    assert "nested_content_too_deep" in str(raised.value)


def _write_valid_manifests(tmp_path: Path) -> tuple[Path, Path]:
    manifest_root = tmp_path / "manifests"
    body_root = tmp_path / "bodies"
    manifest_root.mkdir()
    body_root.mkdir()
    _ = (body_root / "auth_failure.body").write_bytes(b"")
    _ = (body_root / "unavailable.body").write_bytes(b"-1|false")

    response_document: dict[str, object] = {
        "schema": "athena.stable_compatibility.getscores.response_shapes.v1",
        "shapes": [
            {
                "shape_id": "auth_failure",
                "http_status": 401,
                "required_headers": {"content-length": "0"},
                "absent_headers": ["content-type"],
                "body_file": "auth_failure.body",
                "terminal_lf_count": 0,
                "personal_best_present": False,
                "leaderboard_row_count": 0,
            },
            {
                "shape_id": "unavailable",
                "http_status": 200,
                "required_headers": {"content-length": "8"},
                "absent_headers": [],
                "body_file": "unavailable.body",
                "terminal_lf_count": 0,
                "personal_best_present": False,
                "leaderboard_row_count": 0,
            },
        ],
    }
    _write_document(manifest_root / "response_shapes.json", response_document)
    branch_document: dict[str, object] = {
        "schema": "athena.stable_compatibility.getscores.branch_cases.v1",
        "cases": [
            {
                "case_id": "auth-missing",
                "identity_profile": "auth_missing",
                "request_selector": "global_domain",
                "expected_domain_category": None,
                "seed_profile": "none",
                "mutation_profiles": ["request_version_variant"],
                "expected_shape_id": "auth_failure",
                "expected_warning_categories": [],
                "evidence_status": "confirmed",
            }
        ],
    }
    _write_document(manifest_root / "branch_cases.json", branch_document)
    crosswalk_document: dict[str, object] = {
        "schema": "athena.stable_compatibility.getscores.beatmap_status_crosswalk.v1",
        "entries": [],
    }
    _write_document(
        manifest_root / "beatmap_status_crosswalk.json",
        crosswalk_document,
    )
    return manifest_root, body_root


def _crosswalk_entry(
    *,
    getscores_representation: str,
    getscores_wire_status: int | None,
    getscores_sources: tuple[str, ...],
) -> dict[str, object]:
    return {
        "canonical_status": "ranked",
        "getscores": {
            "representation": getscores_representation,
            "wire_status": getscores_wire_status,
            "evidence_status": "confirmed",
            "evidence_sources": list(getscores_sources),
        },
        "beatmap_info": {
            "representation": "unconfirmed",
            "wire_status": None,
            "evidence_status": "unconfirmed",
            "evidence_sources": [],
        },
    }


def _read_document(path: Path) -> dict[str, object]:
    parsed = cast("object", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(parsed, Mapping):
        raise TypeError("test fixture document must be an object")
    mapping = cast("Mapping[str, object]", parsed)
    return dict(mapping)


def _entries(document: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = document[key]
    if not isinstance(value, list):
        raise TypeError("test fixture collection must be a list")
    entries: list[dict[str, object]] = []
    for item in cast("list[object]", value):
        if not isinstance(item, Mapping):
            raise TypeError("test fixture entry must be an object")
        entries.append(cast("dict[str, object]", item))
    return entries


def _write_document(path: Path, document: Mapping[str, object]) -> None:
    _ = path.write_text(json.dumps(document), encoding="utf-8")
