from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import copytree
from typing import TYPE_CHECKING

import athena_cli.stable_verification.getscores as getscores_module
from athena_cli.stable_verification.client import ProbeResponse
from athena_cli.stable_verification.getscores import (
    GETSCORES_WEB_LEGACY_PATH,
    GetscoresVerifier,
    build_getscores_query,
)
from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    GetscoresProbeCase,
    StableSurface,
    StableTarget,
    SurfaceResult,
    VerificationStatus,
)
from athena_cli.stable_verification.osu_py_probe import OsuPyProbePrerequisites

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest


_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"
_GETSCORES_COMPLETION_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_GETSCORES_COMPLETION_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_COMPLETION_EVIDENCE_REFERENCES = (
    "getscores completion response shapes",
    "getscores completion branch cases",
    "getscores completion status crosswalk",
)


def test_verify_fixtures_parses_existing_web_legacy_getscores_bodies() -> None:
    """Legacy fixtureとcompletion evidenceの必須結果を検証する。

    Args:
        なし.

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: Legacy fixtureまたはcompletion evidenceの結果が期待と異なる場合。

    Notes:
        Completion evidenceは3種類のmandatory golden fixtureとして報告される。
    """

    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier()

    results = verifier.verify_fixtures()
    completion_results = _completion_results(results)

    assert results
    assert all(result.surface is StableSurface.GETSCORES for result in results)
    assert all(result.status is VerificationStatus.PASS for result in results)
    assert all(result.evidence_type is EvidenceType.GOLDEN_FIXTURE for result in results)
    assert all(result.scope is EvidenceScope.MANDATORY for result in results)
    assert any("unavailable" in result.diagnostic_summary.message for result in results)
    assert any("empty leaderboard" in result.diagnostic_summary.message for result in results)
    assert tuple(result.reference for result in completion_results) == (
        _COMPLETION_EVIDENCE_REFERENCES
    )
    assert all(result.status is VerificationStatus.PASS for result in completion_results)
    assert {result.diagnostic_summary.message for result in completion_results} == {
        "getscores response shapes validation passed",
        "getscores branch cases validation passed",
        "getscores status crosswalk validation passed",
    }


def test_verify_fixtures_projects_missing_completion_evidence_as_safe_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Completion evidenceの読込失敗が安全な必須失敗結果になることを検証する。

    Args:
        monkeypatch (pytest.MonkeyPatch): Default fixture rootを一時pathへ差し替えるfixture。
        tmp_path (Path): Raw markerを含む存在しないfixture rootを作る一時directory。

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: Failure resultの属性またはredactionが期待と異なる場合。

    Notes:
        Credential, username, raw query, path traversal, internal provenanceを出力しない。
    """

    raw_markers = (
        "credential=credential-sentinel",
        "username=username-sentinel",
        "c=query-sentinel",
        "../path-traversal-sentinel",
        "internal_provenance=provenance-sentinel",
    )
    unsafe_manifest_root = (
        tmp_path / raw_markers[0] / raw_markers[1] / raw_markers[2] / raw_markers[4]
    )
    unsafe_body_root = tmp_path / raw_markers[3]
    monkeypatch.setattr(
        getscores_module,
        "_DEFAULT_COMPLETION_MANIFEST_ROOT",
        unsafe_manifest_root,
    )
    monkeypatch.setattr(
        getscores_module,
        "_DEFAULT_COMPLETION_BODY_ROOT",
        unsafe_body_root,
    )

    results = GetscoresVerifier[OsuPyProbePrerequisites]().verify_fixtures()
    completion_results = _completion_results(results)
    rendered_values = "\n".join(
        value
        for result in completion_results
        for value in (result.diagnostic_summary.message, result.reference or "")
    )

    assert tuple(result.reference for result in completion_results) == (
        _COMPLETION_EVIDENCE_REFERENCES
    )
    assert all(result.status is VerificationStatus.FAIL for result in completion_results)
    assert all(
        result.evidence_type is EvidenceType.GOLDEN_FIXTURE
        and result.scope is EvidenceScope.MANDATORY
        and result.surface is StableSurface.GETSCORES
        for result in completion_results
    )
    assert {result.diagnostic_summary.message for result in completion_results} == {
        "getscores completion evidence validation failed"
    }
    assert str(unsafe_manifest_root) not in rendered_values
    assert str(unsafe_body_root) not in rendered_values
    assert all(marker not in rendered_values for marker in raw_markers)


def test_verify_fixtures_projects_body_validation_failure_by_completion_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Body fixture不正がresponse shapeだけを安全なFAILとして投影することを検証する。

    Args:
        monkeypatch (pytest.MonkeyPatch): Default completion rootを一時copyへ差し替えるfixture。
        tmp_path (Path): Canonical completion evidenceの一時copyを置くdirectory。

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: Surface別のvalidation結果またはredactionが期待と異なる場合。

    Notes:
        Branch caseとstatus crosswalkはbody grammarの独立validatorとしてPASSを維持する。
    """

    raw_markers = (
        "credential=credential-sentinel",
        "username=username-sentinel",
        "c=query-sentinel",
        "../path-traversal-sentinel",
        "internal_provenance=provenance-sentinel",
    )
    manifest_root, body_root = _copy_completion_evidence(tmp_path)
    invalid_body = "\n".join(raw_markers).encode()
    _ = (body_root / "header_with_rows.body.b64").write_bytes(invalid_body)
    monkeypatch.setattr(
        getscores_module,
        "_DEFAULT_COMPLETION_MANIFEST_ROOT",
        manifest_root,
    )
    monkeypatch.setattr(
        getscores_module,
        "_DEFAULT_COMPLETION_BODY_ROOT",
        body_root,
    )

    completion_results = _completion_results(
        GetscoresVerifier[OsuPyProbePrerequisites]().verify_fixtures()
    )
    results_by_reference = {result.reference: result for result in completion_results}
    rendered_values = "\n".join(
        value
        for result in completion_results
        for value in (result.diagnostic_summary.message, result.reference or "")
    )

    assert tuple(results_by_reference) == _COMPLETION_EVIDENCE_REFERENCES
    assert all(
        result.surface is StableSurface.GETSCORES
        and result.evidence_type is EvidenceType.GOLDEN_FIXTURE
        and result.scope is EvidenceScope.MANDATORY
        for result in completion_results
    )
    assert results_by_reference["getscores completion response shapes"].status is (
        VerificationStatus.FAIL
    )
    assert (
        results_by_reference["getscores completion response shapes"].diagnostic_summary.message
        == "getscores response shapes validation failed: 1 error(s)"
    )
    assert results_by_reference["getscores completion branch cases"].status is (
        VerificationStatus.PASS
    )
    assert (
        results_by_reference["getscores completion branch cases"].diagnostic_summary.message
        == "getscores branch cases validation passed"
    )
    assert results_by_reference["getscores completion status crosswalk"].status is (
        VerificationStatus.PASS
    )
    assert (
        results_by_reference["getscores completion status crosswalk"].diagnostic_summary.message
        == "getscores status crosswalk validation passed"
    )
    assert str(manifest_root) not in rendered_values
    assert str(body_root) not in rendered_values
    assert all(marker not in rendered_values for marker in raw_markers)


def test_verify_fixtures_uses_injected_completion_fixture_roots(tmp_path: Path) -> None:
    """Custom completion fixture rootを一貫して検証に使用する。

    Args:
        tmp_path (Path): Completion fixtureの一時copyを作成するdirectory。

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: Injected rootの不正fixtureを既定fixtureへすり替えてPASSにする場合。
    """

    manifest_root, body_root = _copy_completion_evidence(tmp_path)
    _ = (body_root / "header_with_rows.body.b64").write_bytes(b"invalid base64\n")
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        completion_manifest_root=manifest_root,
        completion_body_root=body_root,
    )

    results_by_reference = {
        result.reference: result for result in _completion_results(verifier.verify_fixtures())
    }

    assert results_by_reference["getscores completion response shapes"].status is (
        VerificationStatus.FAIL
    )


def test_load_probe_cases_preserves_stable_query_shape_fields() -> None:
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier()

    cases = verifier.load_probe_cases()

    assert cases
    assert {case.name for case in cases} == {
        "ranked_osu_local_leaderboard",
        "ranked_osu_selected_mods_leaderboard",
        "ranked_osu_friends_leaderboard",
        "ranked_osu_country_leaderboard",
        "ranked_osu_unsupported_leaderboard_type",
        "ranked_osu_mirror_selected_mods_leaderboard",
        "ranked_mania_converted_local_leaderboard",
    }
    assert all(case.checksum for case in cases)
    assert all(case.filename.endswith(".osu") for case in cases)
    assert all(case.beatmapset_id == 1 for case in cases)
    assert {case.mode for case in cases} == {0, 3}
    assert {case.leaderboard_type for case in cases} == {
        "local",
        "selected_mods",
        "friends",
        "country",
        "99",
    }
    assert any(case.mods == 64 for case in cases)
    assert any(case.mods == 1073741824 for case in cases)
    assert all(case.request_version == 4 for case in cases)


def test_build_getscores_query_maps_probe_case_to_stable_web_legacy_shape() -> None:
    case = _probe_case()

    query = build_getscores_query(case)

    assert query == {
        "c": "0123456789abcdef0123456789abcdef",
        "f": "Artist - Title (Mapper) [Difficulty].osu",
        "i": "75",
        "m": "0",
        "mods": "0",
        "v": "1",
        "vv": "4",
    }


def test_build_getscores_query_maps_named_leaderboard_categories() -> None:
    assert build_getscores_query(_probe_case(leaderboard_type="selected_mods"))["v"] == "2"
    assert build_getscores_query(_probe_case(leaderboard_type="friends"))["v"] == "3"
    assert build_getscores_query(_probe_case(leaderboard_type="country"))["v"] == "4"
    assert build_getscores_query(_probe_case(leaderboard_type="99"))["v"] == "99"


def test_probe_target_uses_stable_probe_client_and_parses_response() -> None:
    client = _RecordingGetClient(body=b"2|false|75|1|0||\n0\n[bold:0,size:20]Artist|Title\n10\n")
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        target=_target(),
        client=client,
    )

    result = verifier.probe_target(_probe_case())

    assert client.path == GETSCORES_WEB_LEGACY_PATH
    assert client.query == {
        "c": "0123456789abcdef0123456789abcdef",
        "f": "Artist - Title (Mapper) [Difficulty].osu",
        "i": "75",
        "m": "0",
        "mods": "0",
        "v": "1",
        "vv": "4",
    }
    assert result.status is VerificationStatus.PASS
    assert result.evidence_type is EvidenceType.HEADLESS_PROBE
    assert result.scope is EvidenceScope.OPTIONAL
    assert result.diagnostic_summary.method == "GET"
    assert result.diagnostic_summary.path == GETSCORES_WEB_LEGACY_PATH
    assert "empty leaderboard" in result.diagnostic_summary.message


def test_probe_target_accepts_normal_score_rows_as_implementation_completion() -> None:
    """正常なleaderboard rowをimplementation-completeのPASSとして検証する。

    Args:
        なし.

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: Parsed score rowがPASS以外またはstale gap診断になる場合。

    Notes:
        Malformed responseのFAILとunavailable responseの扱いはこのtestで変更しない。
    """

    client = _RecordingGetClient(
        body=(
            b"2|false|75|1|1||\n"
            b"0\n"
            b"[bold:0,size:20]Artist|Title\n"
            b"10\n"
            b"\n"
            b"1|Player|123456|999|300|100|50|0|0|321|1|0|1|1|1780790400|1\n"
        )
    )
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        target=_target(),
        client=client,
    )

    result = verifier.probe_target(_probe_case())

    assert result.status is VerificationStatus.PASS
    assert result.fails_run is False
    assert "score row" in result.diagnostic_summary.message
    assert "known gap" not in result.diagnostic_summary.message


def test_probe_target_rejects_malformed_score_row_before_reporting_pass() -> None:
    """不正なscore rowを含むtarget responseをPASSとして扱わない。

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: Row grammarが壊れたresponseをtarget probeがPASSとして報告する場合。
    """

    client = _RecordingGetClient(
        body=(
            b"2|false|75|1|1||\n"
            b"0\n"
            b"[bold:0,size:20]Artist|Title\n"
            b"10\n"
            b"\n"
            b"1|Player|123456|999|300|100|50|0|0|321|true|A|1\n"
        )
    )
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        target=_target(),
        client=client,
    )

    result = verifier.probe_target(_probe_case())

    assert result.status is VerificationStatus.FAIL
    assert "score row" in result.diagnostic_summary.message


def test_probe_target_accepts_personal_best_fallback_score_row() -> None:
    client = _RecordingGetClient(
        body=(
            b"2|false|75|1|1||\n"
            b"0\n"
            b"[bold:0,size:20]Artist|Title\n"
            b"10\n"
            b"42|Player|987654|1234|1|2|300|3|4|5|1|24|7|1|1780790400|1\n"
            b"42|Player|987654|1234|1|2|300|3|4|5|1|24|7|1|1780790400|1\n"
        )
    )
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        target=_target(),
        client=client,
    )

    result = verifier.probe_target(_probe_case())

    assert result.status is VerificationStatus.PASS
    assert "personal best" in result.diagnostic_summary.message


def test_optional_osu_py_probe_skips_without_target_or_prerequisites() -> None:
    """Completion fixture検証がoptional osu.py probeのskip条件を変えないことを検証する。

    Args:
        なし.

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: Targetまたはprerequisites未設定時にprobeが実行される場合。

    Notes:
        Fixture検証はmandatoryだが, optional probeのscopeとskip messageは維持する。
    """

    probe = _RecordingOptionalProbe()
    verifier_without_target: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        optional_probe=probe,
        optional_probe_prerequisites=_ready_prerequisites(),
    )
    verifier_without_prerequisites: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        target=_target(), optional_probe=probe
    )

    fixture_results = verifier_without_target.verify_fixtures()
    missing_target = verifier_without_target.probe_optional_client(_probe_case())
    missing_prerequisites = verifier_without_prerequisites.probe_optional_client(_probe_case())

    assert len(_completion_results(fixture_results)) == 3
    assert probe.calls == []
    assert missing_target.status is VerificationStatus.SKIP
    assert missing_target.scope is EvidenceScope.OPTIONAL
    assert missing_target.fails_run is False
    assert missing_target.diagnostic_summary.message == (
        "osu.py getscores probe skipped: target not configured"
    )
    assert missing_prerequisites.status is VerificationStatus.SKIP
    assert missing_prerequisites.diagnostic_summary.message == (
        "osu.py getscores probe skipped: prerequisites not configured"
    )


def test_optional_osu_py_probe_runs_only_with_target_and_prerequisites() -> None:
    probe = _RecordingOptionalProbe()
    prerequisites = _ready_prerequisites()
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        target=_target(),
        optional_probe=probe,
        optional_probe_prerequisites=prerequisites,
    )
    case = _probe_case()

    result = verifier.probe_optional_client(case)

    assert probe.calls == [(case, prerequisites)]
    assert result.status is VerificationStatus.PASS
    assert result.diagnostic_summary.message == "optional probe called"


def _probe_case(
    *,
    leaderboard_type: str = "local",
    mods: int = 0,
) -> GetscoresProbeCase:
    return GetscoresProbeCase(
        name="ranked_fixture",
        checksum="0123456789abcdef0123456789abcdef",
        filename="Artist - Title (Mapper) [Difficulty].osu",
        beatmapset_id=75,
        mode=0,
        mods=mods,
        leaderboard_type=leaderboard_type,
        request_version=4,
    )


def _target() -> StableTarget:
    return StableTarget(
        base_url="http://127.0.0.1:8000",
        host_identity="athena.localhost",
        timeout_seconds=1.0,
    )


def _ready_prerequisites() -> OsuPyProbePrerequisites:
    return OsuPyProbePrerequisites(
        version="20260217",
        executable_sha256="0" * 64,
        credentials_present=True,
    )


@dataclass(slots=True)
class _RecordingGetClient:
    body: bytes
    path: str | None = None
    query: Mapping[str, str] | None = None

    def get_web_legacy(
        self,
        path: str,
        *,
        query: Mapping[str, str],
        host_prefix: str = "osu",
    ) -> ProbeResponse:
        _ = host_prefix
        self.path = path
        self.query = query
        return _probe_response(self.body)


@dataclass(slots=True)
class _RecordingOptionalProbe:
    calls: list[tuple[GetscoresProbeCase, OsuPyProbePrerequisites]]

    def __init__(self) -> None:
        self.calls = []

    def probe_getscores(
        self,
        case: GetscoresProbeCase,
        prerequisites: OsuPyProbePrerequisites,
    ) -> SurfaceResult:
        self.calls.append((case, prerequisites))
        return SurfaceResult(
            surface=StableSurface.GETSCORES,
            status=VerificationStatus.PASS,
            evidence_type=EvidenceType.HEADLESS_PROBE,
            scope=EvidenceScope.OPTIONAL,
            diagnostic_summary=DiagnosticSummary(message="optional probe called"),
            reference="optional:osu.py getscores probe",
        )


def _probe_response(body: bytes) -> ProbeResponse:
    return ProbeResponse(
        status=VerificationStatus.PASS,
        body=body,
        diagnostic_summary=DiagnosticSummary(
            message=f"GET {GETSCORES_WEB_LEGACY_PATH} status=200 bytes={len(body)}",
            method="GET",
            path=GETSCORES_WEB_LEGACY_PATH,
            status_code=200,
            response_byte_size=len(body),
        ),
    )


def _completion_results(
    results: tuple[SurfaceResult, ...],
) -> tuple[SurfaceResult, ...]:
    return tuple(
        result for result in results if result.reference in _COMPLETION_EVIDENCE_REFERENCES
    )


def _copy_completion_evidence(tmp_path: Path) -> tuple[Path, Path]:
    """Canonical completion evidenceを変更しない一時copyとして返す。

    Args:
        tmp_path (Path): Manifestとbody fixtureのcopy先directory。

    Returns:
        tuple[Path, Path]: Copyしたmanifest rootとbody root。

    Raises:
        OSError: Canonical fixtureのcopyに失敗した場合。

    Notes:
        Callerはcopy側だけを変更し, repository上のcanonical fixtureを変更しない。
    """

    manifest_root = tmp_path / "completion-manifests"
    body_root = tmp_path / "completion-bodies"
    _ = copytree(_GETSCORES_COMPLETION_MANIFEST_ROOT, manifest_root)
    _ = copytree(_GETSCORES_COMPLETION_BODY_ROOT, body_root)
    return manifest_root, body_root
