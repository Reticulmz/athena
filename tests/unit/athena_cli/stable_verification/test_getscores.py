from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def test_verify_fixtures_parses_existing_web_legacy_getscores_bodies() -> None:
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier()

    results = verifier.verify_fixtures()

    assert results
    assert all(result.surface is StableSurface.GETSCORES for result in results)
    assert all(result.status is VerificationStatus.PASS for result in results)
    assert all(result.evidence_type is EvidenceType.GOLDEN_FIXTURE for result in results)
    assert all(result.scope is EvidenceScope.MANDATORY for result in results)
    assert any("unavailable" in result.diagnostic_summary.message for result in results)
    assert any("empty leaderboard" in result.diagnostic_summary.message for result in results)


def test_load_probe_cases_preserves_stable_query_shape_fields() -> None:
    verifier: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier()

    cases = verifier.load_probe_cases()

    assert cases
    assert {case.name for case in cases} == {
        "ranked_osu_local_leaderboard",
        "ranked_mania_converted_local_leaderboard",
    }
    assert all(case.checksum for case in cases)
    assert all(case.filename.endswith(".osu") for case in cases)
    assert all(case.beatmapset_id == 1 for case in cases)
    assert {case.mode for case in cases} == {0, 3}
    assert all(case.mods == 0 for case in cases)
    assert all(case.leaderboard_type == "local" for case in cases)
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


def test_probe_target_distinguishes_score_row_known_gap() -> None:
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

    assert result.status is VerificationStatus.KNOWN_GAP
    assert result.fails_run is False
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
    probe = _RecordingOptionalProbe()
    verifier_without_target: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        optional_probe=probe,
        optional_probe_prerequisites=_ready_prerequisites(),
    )
    verifier_without_prerequisites: GetscoresVerifier[OsuPyProbePrerequisites] = GetscoresVerifier(
        target=_target(), optional_probe=probe
    )

    missing_target = verifier_without_target.probe_optional_client(_probe_case())
    missing_prerequisites = verifier_without_prerequisites.probe_optional_client(_probe_case())

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


def _probe_case() -> GetscoresProbeCase:
    return GetscoresProbeCase(
        name="ranked_fixture",
        checksum="0123456789abcdef0123456789abcdef",
        filename="Artist - Title (Mapper) [Difficulty].osu",
        beatmapset_id=75,
        mode=0,
        mods=0,
        leaderboard_type="local",
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
