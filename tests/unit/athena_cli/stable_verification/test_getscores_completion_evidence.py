from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from athena_cli.stable_verification.getscores_evidence import (
    EndpointEvidenceState,
    GetscoresBodyEncoding,
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
from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.compatibility.stable.getscores import GetscoresParseWarning
from osu_server.domain.scores.personal_best import LeaderboardCategory

_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"
_RESPONSE_SHAPES_MANIFEST = (
    _FIXTURE_ROOT / "stable_compatibility" / "getscores" / "response_shapes.json"
)
_BRANCH_CASES_MANIFEST = _FIXTURE_ROOT / "stable_compatibility" / "getscores" / "branch_cases.json"
_STATUS_CROSSWALK_MANIFEST = (
    _FIXTURE_ROOT / "stable_compatibility" / "getscores" / "beatmap_status_crosswalk.json"
)
_COMPLETION_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_OFFICIAL_GETSCORES_SOURCE_PREFIX = "official_fixture:tests/fixtures/web_legacy/getscores/"
_ATHENA_GETSCORES_MAPPER_SOURCE = (
    "athena_deterministic:src/osu_server/transports/stable/web_legacy/mappers/getscores.py"
)
_GETSCORES_STATUS_TEST_SOURCE_PREFIX = (
    "automated_test:tests/unit/transports/web_legacy/test_getscores_status_mapper.py#"
)
_REFERENCE_IMPLEMENTATION_APPROVED_SOURCE = (
    "reference_implementation:osuAkatsuki/bancho.py/blob/"
    "0651b54c66daa839c1bb3998e4f9a8d1173e144d/app/api/domains/osu.py"
)
_BEATMAP_INFO_RANKED_SOURCE = (
    ".kiro:specs/beatmap-info-endpoint/research.md"
    "#observed-official-response-fixture-osu-getbeatmapinfophp"
)

_HEADER_ONLY_BODY = (
    b"2|false|75|1|0||\n"
    b"0\n"
    b"[bold:0,size:20]Fixture Artist Safe Text|Fixture Title Safe Text\n"
    b"0\n"
    b"\n"
    b"\n"
)
_HEADER_WITH_ROWS_BODY = (
    b"2|false|75|1|2||\n"
    b"0\n"
    b"[bold:0,size:20]Fixture Artist Safe Text|Fixture Title Safe Text\n"
    b"0\n"
    b"42|PB Player Safe Text|987654|1234|1|2|300|3|4|5|1|24|7|3|1780790400|1\n"
    b"43|Row One Safe Text|876543|999|4|5|250|6|7|8|0|0|8|1|1780790460|1\n"
    b"44|Row Two Safe Text|765432|888|9|10|200|11|12|13|1|64|9|2|1780790520|0\n"
)

_EXPECTED_RESPONSE_BODIES = {
    GetscoresWireShapeId.AUTH_FAILURE: b"",
    GetscoresWireShapeId.UNAVAILABLE: b"-1|false",
    GetscoresWireShapeId.UPDATE_AVAILABLE: b"1|false",
    GetscoresWireShapeId.HEADER_ONLY: _HEADER_ONLY_BODY,
    GetscoresWireShapeId.HEADER_WITH_ROWS: _HEADER_WITH_ROWS_BODY,
}


def test_load_getscores_completion_evidence_returns_immutable_typed_bundle(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    _ = (manifest_root / "branch_cases.json").write_bytes(_BRANCH_CASES_MANIFEST.read_bytes())

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    assert isinstance(evidence, GetscoresCompletionEvidence)
    assert isinstance(evidence.response_shapes, tuple)
    assert isinstance(evidence.branch_cases, tuple)
    assert isinstance(evidence.status_crosswalk, tuple)
    assert evidence.response_shapes[0].shape_id is GetscoresWireShapeId.AUTH_FAILURE
    assert evidence.branch_cases[0].expected_shape_id is GetscoresWireShapeId.HEADER_WITH_ROWS
    assert evidence.branch_cases[0].evidence_status is GetscoresEvidenceStatus.ATHENA_DETERMINISTIC
    assert evidence.branch_cases[0].mutation_profiles == ()
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
    response_path = manifest_root / "response_shapes.json"
    response_document = _read_document(response_path)
    response_document["shapes"] = [
        entry
        for entry in _entries(response_document, "shapes")
        if entry.get("shape_id") != "header_only"
    ]
    _write_document(response_path, response_document)
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
    _entries(document, "shapes")[0]["body_file"] = "../outside.body.b64"
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "unsafe_body_path" in message
    assert "outside.body.b64" not in message


def test_manifest_rejects_missing_body_file_without_echoing_path(tmp_path: Path) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    _entries(document, "shapes")[0]["body_file"] = "missing-secret-body.body.b64"
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "missing_body_file" in message
    assert "missing-secret-body.body.b64" not in message


def test_manifest_rejects_unknown_body_encoding_without_echoing_value(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_valid_manifests(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    _entries(document, "shapes")[0]["body_encoding"] = "raw-secret-encoding"
    _write_document(response_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert "body_encoding" in message
    assert "invalid_enum" in message
    assert "raw-secret-encoding" not in message


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
    entry = next(
        entry
        for entry in _entries(document, "entries")
        if entry.get("canonical_status") == "ranked"
    )
    _write_document(crosswalk_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    source = evidence.status_crosswalk[0].getscores.evidence_sources[0]
    assert isinstance(source, GetscoresEvidenceSource)
    assert source == ("official_fixture:tests/fixtures/web_legacy/getscores/ranked_response.txt")

    entry["getscores"] = {
        "representation": "wire",
        "wire_status": 2,
        "evidence_status": "official_fixture",
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


def test_status_crosswalk_fixture_records_every_canonical_endpoint_contract(
    tmp_path: Path,
) -> None:
    assert _STATUS_CROSSWALK_MANIFEST.is_file()
    manifest_root, body_root = _write_status_crosswalk_manifest_bundle(tmp_path)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    by_status = {entry.canonical_status: entry for entry in evidence.status_crosswalk}
    assert set(by_status) == set(BeatmapRankStatus)
    assert {
        status: (
            entry.getscores.representation.value,
            entry.getscores.wire_status,
            entry.getscores.evidence_status.value,
            tuple(str(source) for source in entry.getscores.evidence_sources),
        )
        for status, entry in by_status.items()
    } == {
        BeatmapRankStatus.RANKED: _official_getscores_contract("ranked", "wire", 2),
        BeatmapRankStatus.APPROVED: _reference_implementation_getscores_contract(
            "test_approved_maps_to_3", "wire", 3
        ),
        BeatmapRankStatus.LOVED: _official_getscores_contract("loved", "wire", 5),
        BeatmapRankStatus.QUALIFIED: _official_getscores_contract("qualified", "wire", 4),
        BeatmapRankStatus.PENDING: _official_getscores_contract("pending", "wire", 0),
        BeatmapRankStatus.WIP: _official_getscores_contract("wip", "wire", 0),
        BeatmapRankStatus.GRAVEYARD: _official_getscores_contract("graveyard", "wire", 0),
        BeatmapRankStatus.NOT_SUBMITTED: _official_getscores_contract(
            "not_submitted", "unavailable", None
        ),
        BeatmapRankStatus.UNKNOWN: _deterministic_getscores_contract(
            "test_unknown_maps_to_none", "unavailable", None
        ),
    }
    assert {
        status: (
            entry.beatmap_info.representation.value,
            entry.beatmap_info.wire_status,
            entry.beatmap_info.evidence_status.value,
            tuple(str(source) for source in entry.beatmap_info.evidence_sources),
        )
        for status, entry in by_status.items()
    } == {
        **{
            status: ("unconfirmed", None, "unconfirmed", ())
            for status in BeatmapRankStatus
            if status is not BeatmapRankStatus.RANKED
        },
        BeatmapRankStatus.RANKED: (
            "wire",
            1,
            "official_fixture",
            (_BEATMAP_INFO_RANKED_SOURCE,),
        ),
    }


def test_approved_getscores_crosswalk_uses_single_reference_before_athena_corroboration() -> None:
    evidence = load_getscores_completion_evidence(
        _STATUS_CROSSWALK_MANIFEST.parent,
        _COMPLETION_BODY_ROOT,
    )
    approved = next(
        entry
        for entry in evidence.status_crosswalk
        if entry.canonical_status is BeatmapRankStatus.APPROVED
    )

    assert approved.getscores.evidence_status is EndpointEvidenceState.REFERENCE_IMPLEMENTATION
    assert tuple(str(source) for source in approved.getscores.evidence_sources) == (
        _REFERENCE_IMPLEMENTATION_APPROVED_SOURCE,
        _ATHENA_GETSCORES_MAPPER_SOURCE,
        f"{_GETSCORES_STATUS_TEST_SOURCE_PREFIX}test_approved_maps_to_3",
    )


def test_status_crosswalk_markdown_source_resolves_to_canonical_heading_anchor() -> None:
    evidence = load_getscores_completion_evidence(
        _STATUS_CROSSWALK_MANIFEST.parent,
        _COMPLETION_BODY_ROOT,
    )
    ranked = next(
        entry
        for entry in evidence.status_crosswalk
        if entry.canonical_status is BeatmapRankStatus.RANKED
    )
    source = str(ranked.beatmap_info.evidence_sources[0])
    source_prefix, separator, reference = source.partition(":")
    relative_path, fragment_separator, fragment = reference.partition("#")

    assert separator == ":"
    assert fragment_separator == "#"
    source_path = _FIXTURE_ROOT.parents[1] / source_prefix / relative_path
    assert source_path.is_file()
    anchors = {
        _github_markdown_anchor(line)
        for line in source_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("#")
    }
    assert fragment in anchors


def test_status_crosswalk_rejects_missing_canonical_status_without_echoing_value(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_status_crosswalk_manifest_bundle(tmp_path)
    crosswalk_path = manifest_root / "beatmap_status_crosswalk.json"
    document = _read_document(crosswalk_path)
    document["entries"] = [
        entry
        for entry in _entries(document, "entries")
        if entry.get("canonical_status") != "ranked"
    ]
    _write_document(crosswalk_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    result = validate_getscores_completion_evidence(evidence)[2]

    assert result.status is VerificationStatus.FAIL
    message = result.diagnostic_summary.message
    assert "ranked" not in message


def test_status_crosswalk_rejects_duplicate_canonical_status_without_echoing_value(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_status_crosswalk_manifest_bundle(tmp_path)
    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    ranked = evidence.status_crosswalk[0]
    duplicated = replace(
        evidence,
        status_crosswalk=(*evidence.status_crosswalk, ranked),
    )

    result = validate_getscores_completion_evidence(duplicated)[2]

    assert result.status is VerificationStatus.FAIL
    message = result.diagnostic_summary.message
    assert "ranked" not in message


def test_status_crosswalk_validator_rejects_approved_downgrade_to_athena_deterministic(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_status_crosswalk_manifest_bundle(tmp_path)
    crosswalk_path = manifest_root / "beatmap_status_crosswalk.json"
    document = _read_document(crosswalk_path)
    approved = _status_endpoint(document, "approved", "getscores")
    approved["evidence_status"] = "athena_deterministic"
    approved["evidence_sources"] = [
        _ATHENA_GETSCORES_MAPPER_SOURCE,
        f"{_GETSCORES_STATUS_TEST_SOURCE_PREFIX}test_approved_maps_to_3",
    ]
    _write_document(crosswalk_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    result = validate_getscores_completion_evidence(evidence)[2]

    assert result.status is VerificationStatus.FAIL
    assert "athena_deterministic" not in result.diagnostic_summary.message


@pytest.mark.parametrize(
    ("canonical_status", "endpoint_name", "updates", "forbidden_value"),
    [
        ("approved", "getscores", {"wire_status": 99}, "99"),
        (
            "ranked",
            "getscores",
            {"representation": "unavailable", "wire_status": None},
            "unavailable",
        ),
        (
            "approved",
            "getscores",
            {
                "evidence_status": "official_fixture",
                "evidence_sources": [f"{_OFFICIAL_GETSCORES_SOURCE_PREFIX}ranked_response.txt"],
            },
            "approved",
        ),
        (
            "ranked",
            "getscores",
            {"evidence_sources": [f"{_OFFICIAL_GETSCORES_SOURCE_PREFIX}loved_response.txt"]},
            "loved_response.txt",
        ),
        (
            "approved",
            "beatmap_info",
            {
                "representation": "wire",
                "wire_status": 1,
                "evidence_status": "official_fixture",
                "evidence_sources": [_BEATMAP_INFO_RANKED_SOURCE],
            },
            "approved",
        ),
        ("ranked", "beatmap_info", {"wire_status": 2}, "2"),
        ("ranked", "beatmap_info", {"evidence_status": "confirmed"}, "confirmed"),
        (
            "ranked",
            "beatmap_info",
            {"evidence_sources": [f"{_OFFICIAL_GETSCORES_SOURCE_PREFIX}ranked_response.txt"]},
            "ranked_response.txt",
        ),
    ],
)
def test_status_crosswalk_validator_rejects_noncanonical_endpoint_contract(
    tmp_path: Path,
    canonical_status: str,
    endpoint_name: str,
    updates: Mapping[str, object],
    forbidden_value: str,
) -> None:
    manifest_root, body_root = _write_status_crosswalk_manifest_bundle(tmp_path)
    crosswalk_path = manifest_root / "beatmap_status_crosswalk.json"
    document = _read_document(crosswalk_path)
    _status_endpoint(document, canonical_status, endpoint_name).update(updates)
    _write_document(crosswalk_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    result = validate_getscores_completion_evidence(evidence)[2]

    assert result.status is VerificationStatus.FAIL
    assert forbidden_value not in result.diagnostic_summary.message


@pytest.mark.parametrize(
    ("canonical_status", "endpoint_name", "updates", "error_code", "forbidden_value"),
    [
        (
            "ranked",
            "getscores",
            {"evidence_sources": []},
            "evidence_source_required",
            None,
        ),
        (
            "approved",
            "beatmap_info",
            {"wire_status": 3},
            "unconfirmed_wire_status",
            "3",
        ),
        (
            "approved",
            "beatmap_info",
            {
                "evidence_status": "official_fixture",
                "evidence_sources": [_BEATMAP_INFO_RANKED_SOURCE],
            },
            "unconfirmed_representation_requires_unconfirmed_evidence",
            "official_fixture",
        ),
        (
            "approved",
            "beatmap_info",
            {"representation": "unsupported"},
            "unconfirmed_evidence_requires_unconfirmed_representation",
            "unsupported",
        ),
    ],
)
def test_status_crosswalk_loader_rejects_invalid_endpoint_semantics(
    tmp_path: Path,
    canonical_status: str,
    endpoint_name: str,
    updates: Mapping[str, object],
    error_code: str,
    forbidden_value: str | None,
) -> None:
    manifest_root, body_root = _write_status_crosswalk_manifest_bundle(tmp_path)
    crosswalk_path = manifest_root / "beatmap_status_crosswalk.json"
    document = _read_document(crosswalk_path)
    _status_endpoint(document, canonical_status, endpoint_name).update(updates)
    _write_document(crosswalk_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    message = str(raised.value)
    assert error_code in message
    if forbidden_value is not None:
        assert forbidden_value not in message


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


def test_branch_case_catalog_uses_closed_vocabularies_and_known_shape_references(
    tmp_path: Path,
) -> None:
    assert _BRANCH_CASES_MANIFEST.is_file()
    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    assert {profile.value for profile in GetscoresIdentityProfile} == {
        "auth_missing",
        "auth_invalid",
        "known_beatmap",
        "missing_beatmap_identity",
        "invalid_checksum",
        "unavailable_beatmap",
        "update_candidate",
    }
    assert {selector.value for selector in GetscoresRequestSelector} == {
        "global_domain",
        "local",
        "selected_mods",
        "friends",
        "country",
        "song_select",
        "unsupported_leaderboard",
        "unsupported_playstyle",
    }
    assert {profile.value for profile in GetscoresSeedProfile} == {
        "none",
        "ranked_no_scores",
        "ranked_with_rows",
        "selected_mods_supported",
        "selected_mods_unsupported",
        "friends_directional",
        "country_match",
        "country_missing",
        "country_xx",
        "update_candidate",
    }
    assert {profile.value for profile in GetscoresMutationProfile} == {
        "invalid_mode",
        "invalid_mods",
        "invalid_leaderboard_type",
        "invalid_leaderboard_version",
        "invalid_song_select_flag",
        "invalid_anti_cheat_signal",
        "invalid_beatmapset_id_hint",
        "valid_anti_cheat_signal",
        "request_version_variant",
    }
    assert {warning.value for warning in GetscoresParseWarning} == {
        "invalid_mode",
        "invalid_mods",
        "invalid_leaderboard_type",
        "invalid_leaderboard_version",
        "invalid_song_select_flag",
        "invalid_anti_cheat_signal",
        "invalid_beatmapset_id_hint",
    }

    shape_ids = {shape.shape_id for shape in evidence.response_shapes}
    assert evidence.branch_cases
    assert all(case.expected_shape_id in shape_ids for case in evidence.branch_cases)
    assert all(
        case.expected_domain_category is None
        or isinstance(case.expected_domain_category, LeaderboardCategory)
        for case in evidence.branch_cases
    )
    assert all(
        all(
            isinstance(warning, GetscoresParseWarning)
            for warning in case.expected_warning_categories
        )
        for case in evidence.branch_cases
    )


def test_branch_case_catalog_maps_every_selection_profile_deterministically(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    cases = {case.case_id: case for case in evidence.branch_cases}
    expected: dict[
        str,
        tuple[
            GetscoresIdentityProfile,
            GetscoresRequestSelector,
            LeaderboardCategory | None,
            GetscoresSeedProfile,
            GetscoresWireShapeId,
        ],
    ] = {
        "global-with-rows": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.GLOBAL_DOMAIN,
            LeaderboardCategory.GLOBAL,
            GetscoresSeedProfile.RANKED_WITH_ROWS,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "local-maps-global": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.LOCAL,
            LeaderboardCategory.GLOBAL,
            GetscoresSeedProfile.RANKED_WITH_ROWS,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "selected-mods-supported": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.SELECTED_MODS,
            LeaderboardCategory.SELECTED_MODS,
            GetscoresSeedProfile.SELECTED_MODS_SUPPORTED,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "selected-mods-unsupported": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.SELECTED_MODS,
            LeaderboardCategory.SELECTED_MODS,
            GetscoresSeedProfile.SELECTED_MODS_UNSUPPORTED,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "friends-outbound-only": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.FRIENDS,
            LeaderboardCategory.FRIENDS,
            GetscoresSeedProfile.FRIENDS_DIRECTIONAL,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "country-match": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.COUNTRY,
            LeaderboardCategory.COUNTRY,
            GetscoresSeedProfile.COUNTRY_MATCH,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "country-missing": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.COUNTRY,
            LeaderboardCategory.COUNTRY,
            GetscoresSeedProfile.COUNTRY_MISSING,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "country-xx": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.COUNTRY,
            LeaderboardCategory.COUNTRY,
            GetscoresSeedProfile.COUNTRY_XX,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "song-select-header-only": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.SONG_SELECT,
            LeaderboardCategory.GLOBAL,
            GetscoresSeedProfile.RANKED_WITH_ROWS,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "unsupported-leaderboard-header-only": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.UNSUPPORTED_LEADERBOARD,
            None,
            GetscoresSeedProfile.RANKED_WITH_ROWS,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "unsupported-playstyle-header-only": (
            GetscoresIdentityProfile.KNOWN_BEATMAP,
            GetscoresRequestSelector.UNSUPPORTED_PLAYSTYLE,
            LeaderboardCategory.GLOBAL,
            GetscoresSeedProfile.RANKED_WITH_ROWS,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "unavailable-beatmap": (
            GetscoresIdentityProfile.UNAVAILABLE_BEATMAP,
            GetscoresRequestSelector.GLOBAL_DOMAIN,
            LeaderboardCategory.GLOBAL,
            GetscoresSeedProfile.NONE,
            GetscoresWireShapeId.UNAVAILABLE,
        ),
        "update-candidate": (
            GetscoresIdentityProfile.UPDATE_CANDIDATE,
            GetscoresRequestSelector.GLOBAL_DOMAIN,
            LeaderboardCategory.GLOBAL,
            GetscoresSeedProfile.UPDATE_CANDIDATE,
            GetscoresWireShapeId.UPDATE_AVAILABLE,
        ),
    }

    assert set(expected) <= set(cases)
    for case_id, expected_signature in expected.items():
        case = cases[case_id]
        assert (
            case.identity_profile,
            case.request_selector,
            case.expected_domain_category,
            case.seed_profile,
            case.expected_shape_id,
        ) == expected_signature
        assert case.mutation_profiles == ()
        assert case.expected_warning_categories == ()
        assert case.evidence_status is GetscoresEvidenceStatus.ATHENA_DETERMINISTIC


def test_branch_case_catalog_marks_malformed_identity_and_optional_fields_provisional(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    cases = {case.case_id: case for case in evidence.branch_cases}

    identity_cases = {
        "missing-beatmap-identity": GetscoresIdentityProfile.MISSING_BEATMAP_IDENTITY,
        "invalid-checksum": GetscoresIdentityProfile.INVALID_CHECKSUM,
    }
    for case_id, identity_profile in identity_cases.items():
        case = cases[case_id]
        assert case.identity_profile is identity_profile
        assert case.request_selector is GetscoresRequestSelector.GLOBAL_DOMAIN
        assert case.expected_domain_category is None
        assert case.seed_profile is GetscoresSeedProfile.NONE
        assert case.mutation_profiles == ()
        assert case.expected_shape_id is GetscoresWireShapeId.UNAVAILABLE
        assert case.expected_warning_categories == ()
        assert case.evidence_status is GetscoresEvidenceStatus.PROVISIONAL_ATHENA_BEHAVIOR

    optional_cases: dict[
        str,
        tuple[
            GetscoresMutationProfile,
            GetscoresParseWarning,
            GetscoresRequestSelector,
            LeaderboardCategory | None,
            GetscoresWireShapeId,
        ],
    ] = {
        "malformed-mode": (
            GetscoresMutationProfile.INVALID_MODE,
            GetscoresParseWarning.INVALID_MODE,
            GetscoresRequestSelector.LOCAL,
            LeaderboardCategory.GLOBAL,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "malformed-mods": (
            GetscoresMutationProfile.INVALID_MODS,
            GetscoresParseWarning.INVALID_MODS,
            GetscoresRequestSelector.LOCAL,
            LeaderboardCategory.GLOBAL,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "malformed-leaderboard-type": (
            GetscoresMutationProfile.INVALID_LEADERBOARD_TYPE,
            GetscoresParseWarning.INVALID_LEADERBOARD_TYPE,
            GetscoresRequestSelector.UNSUPPORTED_LEADERBOARD,
            None,
            GetscoresWireShapeId.HEADER_ONLY,
        ),
        "malformed-leaderboard-version": (
            GetscoresMutationProfile.INVALID_LEADERBOARD_VERSION,
            GetscoresParseWarning.INVALID_LEADERBOARD_VERSION,
            GetscoresRequestSelector.LOCAL,
            LeaderboardCategory.GLOBAL,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "malformed-song-select-flag": (
            GetscoresMutationProfile.INVALID_SONG_SELECT_FLAG,
            GetscoresParseWarning.INVALID_SONG_SELECT_FLAG,
            GetscoresRequestSelector.LOCAL,
            LeaderboardCategory.GLOBAL,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "malformed-anti-cheat-signal": (
            GetscoresMutationProfile.INVALID_ANTI_CHEAT_SIGNAL,
            GetscoresParseWarning.INVALID_ANTI_CHEAT_SIGNAL,
            GetscoresRequestSelector.LOCAL,
            LeaderboardCategory.GLOBAL,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
        "malformed-beatmapset-hint": (
            GetscoresMutationProfile.INVALID_BEATMAPSET_ID_HINT,
            GetscoresParseWarning.INVALID_BEATMAPSET_ID_HINT,
            GetscoresRequestSelector.LOCAL,
            LeaderboardCategory.GLOBAL,
            GetscoresWireShapeId.HEADER_WITH_ROWS,
        ),
    }
    for case_id, expected in optional_cases.items():
        mutation, warning, selector, category, shape_id = expected
        case = cases[case_id]
        assert case.identity_profile is GetscoresIdentityProfile.KNOWN_BEATMAP
        assert case.request_selector is selector
        assert case.expected_domain_category is category
        assert case.seed_profile is GetscoresSeedProfile.RANKED_WITH_ROWS
        assert case.mutation_profiles == (mutation,)
        assert case.expected_shape_id is shape_id
        assert case.expected_warning_categories == (warning,)
        assert case.evidence_status is GetscoresEvidenceStatus.PROVISIONAL_ATHENA_BEHAVIOR

    multiple = cases["malformed-multiple-optional-fields"]
    assert multiple.mutation_profiles == tuple(profile for profile, *_ in optional_cases.values())
    assert multiple.expected_warning_categories == tuple(
        warning for _, warning, *_ in optional_cases.values()
    )
    assert multiple.request_selector is GetscoresRequestSelector.UNSUPPORTED_LEADERBOARD
    assert multiple.expected_domain_category is None
    assert multiple.expected_shape_id is GetscoresWireShapeId.HEADER_ONLY
    assert multiple.evidence_status is GetscoresEvidenceStatus.PROVISIONAL_ATHENA_BEHAVIOR


def test_branch_case_catalog_exercises_every_symbolic_profile_and_invariant_mutation(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    cases = {case.case_id: case for case in evidence.branch_cases}

    assert {case.identity_profile for case in evidence.branch_cases} == set(
        GetscoresIdentityProfile
    )
    assert {case.request_selector for case in evidence.branch_cases} == set(
        GetscoresRequestSelector
    )
    assert {case.seed_profile for case in evidence.branch_cases} == set(GetscoresSeedProfile)
    assert {
        mutation for case in evidence.branch_cases for mutation in case.mutation_profiles
    } == set(GetscoresMutationProfile)
    assert {
        warning for case in evidence.branch_cases for warning in case.expected_warning_categories
    } == set(GetscoresParseWarning)

    for case_id, identity_profile in (
        ("auth-missing", GetscoresIdentityProfile.AUTH_MISSING),
        ("auth-invalid", GetscoresIdentityProfile.AUTH_INVALID),
    ):
        case = cases[case_id]
        assert case.identity_profile is identity_profile
        assert case.expected_domain_category is None
        assert case.seed_profile is GetscoresSeedProfile.NONE
        assert case.expected_shape_id is GetscoresWireShapeId.AUTH_FAILURE
        assert case.expected_warning_categories == ()
        assert case.evidence_status is GetscoresEvidenceStatus.ATHENA_DETERMINISTIC

    no_scores = cases["global-no-scores"]
    assert no_scores.request_selector is GetscoresRequestSelector.GLOBAL_DOMAIN
    assert no_scores.expected_domain_category is LeaderboardCategory.GLOBAL
    assert no_scores.seed_profile is GetscoresSeedProfile.RANKED_NO_SCORES
    assert no_scores.expected_shape_id is GetscoresWireShapeId.HEADER_ONLY

    invariant_cases = {
        "valid-anti-cheat-signal-invariant": GetscoresMutationProfile.VALID_ANTI_CHEAT_SIGNAL,
        "request-version-variant-invariant": GetscoresMutationProfile.REQUEST_VERSION_VARIANT,
    }
    for case_id, mutation in invariant_cases.items():
        case = cases[case_id]
        assert case.request_selector is GetscoresRequestSelector.LOCAL
        assert case.expected_domain_category is LeaderboardCategory.GLOBAL
        assert case.seed_profile is GetscoresSeedProfile.RANKED_WITH_ROWS
        assert case.mutation_profiles == (mutation,)
        assert case.expected_shape_id is GetscoresWireShapeId.HEADER_WITH_ROWS
        assert case.expected_warning_categories == ()
        assert case.evidence_status is GetscoresEvidenceStatus.ATHENA_DETERMINISTIC


def test_branch_case_validation_rejects_empty_catalog(tmp_path: Path) -> None:
    """空のbranch catalogをmandatory evidence failureとして扱う。

    Args:
        tmp_path (Path): Manifest bundleを隔離して作成する一時directory。

    Returns:
        None: 空のcatalogがPASSにならないことを検証する。

    Raises:
        AssertionError: Branch evidenceがFAILにならない場合。
    """

    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    document["cases"] = []
    _write_document(branch_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    branch_result = validate_getscores_completion_evidence(evidence)[1]

    assert branch_result.status is VerificationStatus.FAIL


def test_branch_case_manifest_rejects_missing_cases_collection(tmp_path: Path) -> None:
    """`cases` collectionを持たないbranch manifestを安全に拒否する。

    Args:
        tmp_path (Path): Manifest bundleを隔離して作成する一時directory。

    Returns:
        None: Loaderがmissing collectionをvalidation errorへ変換することを検証する。

    Raises:
        AssertionError: Loaderが不正manifestを受理する, または安全なerror codeを返さない場合。
    """

    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    _ = document.pop("cases")
    _write_document(branch_path, document)

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = load_getscores_completion_evidence(manifest_root, body_root)

    assert "branch_cases.json" in str(raised.value)
    assert "collection_must_be_list" in str(raised.value)


@pytest.mark.parametrize(
    "missing_case_id",
    [
        "auth-missing",
        "unsupported-playstyle-header-only",
        "valid-anti-cheat-signal-invariant",
    ],
)
def test_branch_case_validation_rejects_missing_required_profile(
    tmp_path: Path,
    missing_case_id: str,
) -> None:
    """必須profileを失ったbranch catalogを拒否する。

    Args:
        tmp_path (Path): Manifest bundleを隔離して作成する一時directory。
        missing_case_id (str): 一意のidentity, selector, またはmutationを持つ削除対象case ID。

    Returns:
        None: 不完全なprofile coverageがPASSにならないことを検証する。

    Raises:
        AssertionError: Branch evidenceがFAILにならない場合。
    """

    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    document["cases"] = [
        case for case in _entries(document, "cases") if case.get("case_id") != missing_case_id
    ]
    _write_document(branch_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    branch_result = validate_getscores_completion_evidence(evidence)[1]

    assert branch_result.status is VerificationStatus.FAIL


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("expected_warning_categories", []),
        ("mutation_profiles", ["invalid_mode", "invalid_mode"]),
        ("expected_warning_categories", ["invalid_mode", "invalid_mode"]),
    ],
)
def test_branch_case_validation_rejects_non_set_mutation_warning_contract(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    malformed_mode = next(
        case for case in _entries(document, "cases") if case.get("case_id") == "malformed-mode"
    )
    malformed_mode[field] = invalid_value
    _write_document(branch_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    branch_result = validate_getscores_completion_evidence(evidence)[1]

    assert branch_result.status is VerificationStatus.FAIL


@pytest.mark.parametrize(
    "case_id",
    ["missing-beatmap-identity", "invalid-checksum", "malformed-mode"],
)
def test_branch_case_validation_rejects_non_provisional_malformed_contract(
    tmp_path: Path,
    case_id: str,
) -> None:
    manifest_root, body_root = _write_branch_case_manifest_bundle(tmp_path)
    branch_path = manifest_root / "branch_cases.json"
    document = _read_document(branch_path)
    malformed_case = next(
        case for case in _entries(document, "cases") if case.get("case_id") == case_id
    )
    malformed_case["evidence_status"] = "athena_deterministic"
    _write_document(branch_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    branch_result = validate_getscores_completion_evidence(evidence)[1]

    assert branch_result.status is VerificationStatus.FAIL


def test_versioned_response_shape_fixture_defines_five_exact_wire_contracts(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)

    evidence = load_getscores_completion_evidence(
        manifest_root,
        body_root,
    )

    shapes = {shape.shape_id: shape for shape in evidence.response_shapes}
    assert set(shapes) == set(GetscoresWireShapeId)
    assert len({shape.body_file for shape in shapes.values()}) == 5

    expected_status = {
        GetscoresWireShapeId.AUTH_FAILURE: 401,
        GetscoresWireShapeId.UNAVAILABLE: 200,
        GetscoresWireShapeId.UPDATE_AVAILABLE: 200,
        GetscoresWireShapeId.HEADER_ONLY: 200,
        GetscoresWireShapeId.HEADER_WITH_ROWS: 200,
    }
    expected_terminal_lf = {
        GetscoresWireShapeId.AUTH_FAILURE: 0,
        GetscoresWireShapeId.UNAVAILABLE: 0,
        GetscoresWireShapeId.UPDATE_AVAILABLE: 0,
        GetscoresWireShapeId.HEADER_ONLY: 3,
        GetscoresWireShapeId.HEADER_WITH_ROWS: 1,
    }
    expected_personal_best = {
        GetscoresWireShapeId.AUTH_FAILURE: False,
        GetscoresWireShapeId.UNAVAILABLE: False,
        GetscoresWireShapeId.UPDATE_AVAILABLE: False,
        GetscoresWireShapeId.HEADER_ONLY: False,
        GetscoresWireShapeId.HEADER_WITH_ROWS: True,
    }
    expected_row_count = {
        GetscoresWireShapeId.AUTH_FAILURE: 0,
        GetscoresWireShapeId.UNAVAILABLE: 0,
        GetscoresWireShapeId.UPDATE_AVAILABLE: 0,
        GetscoresWireShapeId.HEADER_ONLY: 0,
        GetscoresWireShapeId.HEADER_WITH_ROWS: 2,
    }

    for shape_id, expected_body in _EXPECTED_RESPONSE_BODIES.items():
        shape = shapes[shape_id]
        expected_content_type = (
            {}
            if shape_id is GetscoresWireShapeId.AUTH_FAILURE
            else {"content-type": "text/plain; charset=utf-8"}
        )
        assert shape.http_status == expected_status[shape_id]
        assert dict(shape.required_headers) == {
            "content-length": str(len(expected_body)),
            **expected_content_type,
        }
        assert shape.absent_headers == (
            ("content-type", "content-encoding", "transfer-encoding")
            if shape_id is GetscoresWireShapeId.AUTH_FAILURE
            else ("content-encoding", "transfer-encoding")
        )
        assert shape.body_encoding is GetscoresBodyEncoding.BASE64
        assert shape.body_file.name == f"{shape_id.value}.body.b64"
        assert shape.body_file.read_bytes() == _encode_body_fixture(expected_body)
        assert shape.read_body_bytes() == expected_body
        assert shape.terminal_lf_count == expected_terminal_lf[shape_id]
        assert (
            len(expected_body) - len(expected_body.rstrip(b"\n")) == expected_terminal_lf[shape_id]
        )
        assert shape.personal_best_present is expected_personal_best[shape_id]
        assert shape.leaderboard_row_count == expected_row_count[shape_id]

    row_lines = _HEADER_WITH_ROWS_BODY.split(b"\n")
    assert row_lines[0].split(b"|")[4] == b"2"
    assert len(row_lines[4].split(b"|")) == 16
    assert len(row_lines[5:-1]) == 2
    assert all(len(row.split(b"|")) == 16 for row in row_lines[5:-1])
    assert b"Fixture Artist Safe Text|Fixture Title Safe Text" in _HEADER_WITH_ROWS_BODY
    assert b"PB Player Safe Text" in _HEADER_WITH_ROWS_BODY
    assert b"Row One Safe Text" in _HEADER_WITH_ROWS_BODY
    assert b"\r" not in _HEADER_WITH_ROWS_BODY

    shape_result = validate_getscores_completion_evidence(evidence)[0]
    assert shape_result.status is VerificationStatus.PASS


@pytest.mark.parametrize(
    ("shape_id", "field", "invalid_value"),
    [
        ("auth_failure", "http_status", 200),
        (
            "unavailable",
            "required_headers",
            {"content-length": "8"},
        ),
        ("auth_failure", "absent_headers", []),
        ("header_only", "terminal_lf_count", 2),
        ("header_with_rows", "personal_best_present", False),
        ("header_with_rows", "leaderboard_row_count", 3),
        ("header_only", "body_file", "header_with_rows.body.b64"),
    ],
)
def test_response_shape_validation_rejects_invalid_manifest_invariants(
    tmp_path: Path,
    shape_id: str,
    field: str,
    invalid_value: object,
) -> None:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    entry = next(
        candidate
        for candidate in _entries(document, "shapes")
        if candidate.get("shape_id") == shape_id
    )
    entry[field] = invalid_value
    _write_document(response_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    shape_result = validate_getscores_completion_evidence(evidence)[0]
    assert shape_result.status is VerificationStatus.FAIL


def test_response_shape_validation_requires_all_five_distinct_shapes(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)
    response_path = manifest_root / "response_shapes.json"
    document = _read_document(response_path)
    document["shapes"] = _entries(document, "shapes")[:-1]
    _write_document(response_path, document)

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    shape_result = validate_getscores_completion_evidence(evidence)[0]
    assert shape_result.status is VerificationStatus.FAIL


@pytest.mark.parametrize(
    ("shape_id", "invalid_body"),
    [
        (GetscoresWireShapeId.UNAVAILABLE, b"-2|false"),
        (GetscoresWireShapeId.UPDATE_AVAILABLE, b"2|false"),
        (GetscoresWireShapeId.HEADER_ONLY, _HEADER_ONLY_BODY[:-1] + b"X"),
        (
            GetscoresWireShapeId.HEADER_WITH_ROWS,
            _HEADER_WITH_ROWS_BODY.replace(b"|2||\n", b"|3||\n", 1),
        ),
        (
            GetscoresWireShapeId.HEADER_WITH_ROWS,
            _HEADER_WITH_ROWS_BODY.replace(b"42|PB", b"42/PB", 1),
        ),
        (
            GetscoresWireShapeId.HEADER_WITH_ROWS,
            _HEADER_WITH_ROWS_BODY.replace(
                b"Fixture Artist",
                b"Fixture\rArtist",
                1,
            ),
        ),
    ],
)
def test_response_shape_validation_rejects_invalid_body_grammar(
    tmp_path: Path,
    shape_id: GetscoresWireShapeId,
    invalid_body: bytes,
) -> None:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)
    _ = (body_root / f"{shape_id.value}.body.b64").write_bytes(_encode_body_fixture(invalid_body))

    evidence = load_getscores_completion_evidence(manifest_root, body_root)

    shape_result = validate_getscores_completion_evidence(evidence)[0]
    assert shape_result.status is VerificationStatus.FAIL


@pytest.mark.parametrize(
    ("encoded_body", "error_code"),
    [
        (b"\n", "non_canonical_base64"),
        (b"YQ==", "invalid_base64_terminal_lf"),
        (b"YQ==\n\n", "invalid_base64_terminal_lf"),
        (b"Y Q==\n", "invalid_base64_whitespace"),
        ("é\n".encode(), "invalid_base64_non_ascii"),
        (b"raw-secret-value!\n", "invalid_base64_payload"),
        (b"YR==\n", "non_canonical_base64"),
    ],
)
def test_public_body_decoder_rejects_invalid_base64_without_echoing_payload(
    tmp_path: Path,
    encoded_body: bytes,
    error_code: str,
) -> None:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)
    target = body_root / "unavailable.body.b64"
    _ = target.write_bytes(encoded_body)
    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    shape = next(
        fixture
        for fixture in evidence.response_shapes
        if fixture.shape_id is GetscoresWireShapeId.UNAVAILABLE
    )

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = shape.read_body_bytes()

    message = str(raised.value)
    assert error_code in message
    assert "raw-secret-value" not in message


def test_public_body_decoder_rejects_unsupported_encoding_without_echoing_value(
    tmp_path: Path,
) -> None:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)
    evidence = load_getscores_completion_evidence(manifest_root, body_root)
    shape = next(
        fixture
        for fixture in evidence.response_shapes
        if fixture.shape_id is GetscoresWireShapeId.UNAVAILABLE
    )
    invalid_shape = replace(shape)
    object.__setattr__(invalid_shape, "body_encoding", "raw-secret-encoding")

    with pytest.raises(GetscoresEvidenceValidationError) as raised:
        _ = invalid_shape.read_body_bytes()

    message = str(raised.value)
    assert "unsupported_body_encoding" in message
    assert "raw-secret-encoding" not in message


def _write_valid_manifests(tmp_path: Path) -> tuple[Path, Path]:
    manifest_root = tmp_path / "manifests"
    body_root = tmp_path / "bodies"
    manifest_root.mkdir()
    body_root.mkdir()
    for shape_id, body in _EXPECTED_RESPONSE_BODIES.items():
        _ = (body_root / f"{shape_id.value}.body.b64").write_bytes(_encode_body_fixture(body))

    response_document: dict[str, object] = {
        "schema": "athena.stable_compatibility.getscores.response_shapes.v1",
        "shapes": [
            {
                "shape_id": "auth_failure",
                "http_status": 401,
                "required_headers": {"content-length": "0"},
                "absent_headers": [
                    "content-type",
                    "content-encoding",
                    "transfer-encoding",
                ],
                "body_file": "auth_failure.body.b64",
                "body_encoding": "base64",
                "terminal_lf_count": 0,
                "personal_best_present": False,
                "leaderboard_row_count": 0,
            },
            {
                "shape_id": "unavailable",
                "http_status": 200,
                "required_headers": {
                    "content-length": "8",
                    "content-type": "text/plain; charset=utf-8",
                },
                "absent_headers": ["content-encoding", "transfer-encoding"],
                "body_file": "unavailable.body.b64",
                "body_encoding": "base64",
                "terminal_lf_count": 0,
                "personal_best_present": False,
                "leaderboard_row_count": 0,
            },
            {
                "shape_id": "update_available",
                "http_status": 200,
                "required_headers": {
                    "content-length": "7",
                    "content-type": "text/plain; charset=utf-8",
                },
                "absent_headers": ["content-encoding", "transfer-encoding"],
                "body_file": "update_available.body.b64",
                "body_encoding": "base64",
                "terminal_lf_count": 0,
                "personal_best_present": False,
                "leaderboard_row_count": 0,
            },
            {
                "shape_id": "header_only",
                "http_status": 200,
                "required_headers": {
                    "content-length": str(len(_HEADER_ONLY_BODY)),
                    "content-type": "text/plain; charset=utf-8",
                },
                "absent_headers": ["content-encoding", "transfer-encoding"],
                "body_file": "header_only.body.b64",
                "body_encoding": "base64",
                "terminal_lf_count": 3,
                "personal_best_present": False,
                "leaderboard_row_count": 0,
            },
            {
                "shape_id": "header_with_rows",
                "http_status": 200,
                "required_headers": {
                    "content-length": str(len(_HEADER_WITH_ROWS_BODY)),
                    "content-type": "text/plain; charset=utf-8",
                },
                "absent_headers": ["content-encoding", "transfer-encoding"],
                "body_file": "header_with_rows.body.b64",
                "body_encoding": "base64",
                "terminal_lf_count": 1,
                "personal_best_present": True,
                "leaderboard_row_count": 2,
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
    _ = (manifest_root / "beatmap_status_crosswalk.json").write_bytes(
        _STATUS_CROSSWALK_MANIFEST.read_bytes()
    )
    return manifest_root, body_root


def _write_response_shape_manifest_bundle(tmp_path: Path) -> tuple[Path, Path]:
    manifest_root = tmp_path / "manifests"
    body_root = tmp_path / "bodies"
    manifest_root.mkdir()
    body_root.mkdir()
    _ = (manifest_root / "response_shapes.json").write_bytes(
        _RESPONSE_SHAPES_MANIFEST.read_bytes()
    )
    for source in _COMPLETION_BODY_ROOT.iterdir():
        if source.is_file():
            _ = (body_root / source.name).write_bytes(source.read_bytes())
    _write_document(
        manifest_root / "branch_cases.json",
        {
            "schema": "athena.stable_compatibility.getscores.branch_cases.v1",
            "cases": [],
        },
    )
    _write_document(
        manifest_root / "beatmap_status_crosswalk.json",
        {
            "schema": "athena.stable_compatibility.getscores.beatmap_status_crosswalk.v1",
            "entries": [],
        },
    )
    return manifest_root, body_root


def _write_branch_case_manifest_bundle(tmp_path: Path) -> tuple[Path, Path]:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)
    _ = (manifest_root / "branch_cases.json").write_bytes(_BRANCH_CASES_MANIFEST.read_bytes())
    return manifest_root, body_root


def _write_status_crosswalk_manifest_bundle(tmp_path: Path) -> tuple[Path, Path]:
    manifest_root, body_root = _write_response_shape_manifest_bundle(tmp_path)
    _ = (manifest_root / "beatmap_status_crosswalk.json").write_bytes(
        _STATUS_CROSSWALK_MANIFEST.read_bytes()
    )
    return manifest_root, body_root


def _official_getscores_contract(
    fixture_stem: str,
    representation: str,
    wire_status: int | None,
) -> tuple[str, int | None, str, tuple[str, ...]]:
    return (
        representation,
        wire_status,
        "official_fixture",
        (f"{_OFFICIAL_GETSCORES_SOURCE_PREFIX}{fixture_stem}_response.txt",),
    )


def _deterministic_getscores_contract(
    test_anchor: str,
    representation: str,
    wire_status: int | None,
) -> tuple[str, int | None, str, tuple[str, ...]]:
    return (
        representation,
        wire_status,
        "athena_deterministic",
        (
            _ATHENA_GETSCORES_MAPPER_SOURCE,
            f"{_GETSCORES_STATUS_TEST_SOURCE_PREFIX}{test_anchor}",
        ),
    )


def _reference_implementation_getscores_contract(
    test_anchor: str,
    representation: str,
    wire_status: int | None,
) -> tuple[str, int | None, str, tuple[str, ...]]:
    return (
        representation,
        wire_status,
        "reference_implementation",
        (
            _REFERENCE_IMPLEMENTATION_APPROVED_SOURCE,
            _ATHENA_GETSCORES_MAPPER_SOURCE,
            f"{_GETSCORES_STATUS_TEST_SOURCE_PREFIX}{test_anchor}",
        ),
    )


def _status_endpoint(
    document: Mapping[str, object],
    canonical_status: str,
    endpoint_name: str,
) -> dict[str, object]:
    entry = next(
        entry
        for entry in _entries(document, "entries")
        if entry.get("canonical_status") == canonical_status
    )
    return cast("dict[str, object]", entry[endpoint_name])


def _github_markdown_anchor(heading_line: str) -> str:
    heading = heading_line.lstrip("#").strip().lower()
    safe_characters = "".join(
        character for character in heading if character.isalnum() or character in {" ", "-", "_"}
    )
    return "-".join(safe_characters.split())


def _encode_body_fixture(body: bytes) -> bytes:
    if not body:
        return b""
    return base64.b64encode(body) + b"\n"


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
