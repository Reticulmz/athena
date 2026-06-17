from __future__ import annotations

from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    GetscoresProbeCase,
    StableSurface,
    SurfaceResult,
    VerificationStatus,
)
from athena_cli.stable_verification.osu_py_probe import (
    OsuPyProbe,
    OsuPyProbePrerequisites,
)


def test_missing_osu_package_becomes_optional_skip() -> None:
    def missing_import() -> object:
        raise ModuleNotFoundError("No module named 'osu'", name="osu")

    probe = OsuPyProbe(import_osu=missing_import)

    result = probe.probe_getscores(_probe_case(), _ready_prerequisites())

    assert result.surface is StableSurface.GETSCORES
    assert result.status is VerificationStatus.SKIP
    assert result.evidence_type is EvidenceType.HEADLESS_PROBE
    assert result.scope is EvidenceScope.OPTIONAL
    assert result.fails_run is False
    assert result.diagnostic_summary.message == "osu.py package is not installed"


def test_missing_prerequisites_skip_before_import_or_request() -> None:
    import_called = False
    executor_called = False

    def import_osu() -> object:
        nonlocal import_called
        import_called = True
        return object()

    def executor(osu_module: object, case: GetscoresProbeCase) -> SurfaceResult:
        nonlocal executor_called
        executor_called = True
        return _pass_result(f"{osu_module!r} {case.name}")

    probe = OsuPyProbe(import_osu=import_osu, executor=executor)

    result = probe.probe_getscores(
        _probe_case(),
        OsuPyProbePrerequisites(
            version="20260217",
            executable_sha256=None,
            credentials_present=True,
        ),
    )

    assert import_called is False
    assert executor_called is False
    assert result.status is VerificationStatus.SKIP
    assert result.fails_run is False
    assert result.diagnostic_summary.message == (
        "osu.py probe prerequisites missing: executable_sha256"
    )


def test_installed_osu_package_uses_injected_getscores_executor() -> None:
    fake_osu_module = object()
    observed_case: GetscoresProbeCase | None = None
    observed_osu_module: object | None = None

    def import_osu() -> object:
        return fake_osu_module

    def executor(osu_module: object, case: GetscoresProbeCase) -> SurfaceResult:
        nonlocal observed_case, observed_osu_module
        observed_case = case
        observed_osu_module = osu_module
        return _pass_result("osu.py getscores probe parsed leaderboard")

    probe = OsuPyProbe(import_osu=import_osu, executor=executor)
    case = _probe_case()

    result = probe.probe_getscores(case, _ready_prerequisites())

    assert observed_osu_module is fake_osu_module
    assert observed_case == case
    assert result.status is VerificationStatus.PASS
    assert result.evidence_type is EvidenceType.HEADLESS_PROBE
    assert result.scope is EvidenceScope.OPTIONAL
    assert result.diagnostic_summary.message == "osu.py getscores probe parsed leaderboard"


def test_executor_error_becomes_optional_unavailable() -> None:
    def executor(osu_module: object, case: GetscoresProbeCase) -> SurfaceResult:
        _ = (osu_module, case)
        raise RuntimeError("local client failed")

    probe = OsuPyProbe(import_osu=object, executor=executor)

    result = probe.probe_getscores(_probe_case(), _ready_prerequisites())

    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.fails_run is False
    assert result.diagnostic_summary.message == ("osu.py getscores probe failed: RuntimeError")


def _probe_case() -> GetscoresProbeCase:
    return GetscoresProbeCase(
        name="ranked_fixture",
        checksum="0123456789abcdef0123456789abcdef",
        filename="Artist - Title (Mapper) [Difficulty].osu",
        beatmapset_id=75,
        mode=0,
        mods=0,
        leaderboard_type="local",
        request_version=3,
    )


def _ready_prerequisites() -> OsuPyProbePrerequisites:
    return OsuPyProbePrerequisites(
        version="20260217",
        executable_sha256="0" * 64,
        credentials_present=True,
    )


def _pass_result(message: str) -> SurfaceResult:
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=VerificationStatus.PASS,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="optional:osu.py getscores probe",
    )
