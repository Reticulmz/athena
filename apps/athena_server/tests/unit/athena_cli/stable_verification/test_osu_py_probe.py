"""任意のosu.py getscores probeの前提判定とerror正規化を検証する."""

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
    """osu.py未導入がrunを失敗させないoptional skipになることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: surface, evidence, scope, または診断messageが変化した場合.
    """

    def missing_import() -> object:
        """osu.py packageが存在しない状態を再現する.

        Raises:
            ModuleNotFoundError: `osu` package未導入を再現するため常に送出する.
        """
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
    """不足前提がimportとexecutorの前にoptional skipされることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: 未設定fieldの診断または依存呼出順が変化した場合.
    """
    import_called = False
    executor_called = False

    def import_osu() -> object:
        """test用のosu.py module objectを返し呼出しを記録する.

        Returns:
            object: executorへ渡すtest用module object.
        """
        nonlocal import_called
        import_called = True
        return object()

    def executor(osu_module: object, case: GetscoresProbeCase) -> SurfaceResult:
        """test用executorの呼出しを記録して成功結果を返す.

        Args:
            osu_module (object): import関数が返したtest用module object.
            case (GetscoresProbeCase): executorへ渡されるgetscores probe case.

        Returns:
            SurfaceResult: 呼出し内容を含むpass結果.
        """
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
    """導入済みosu.py moduleとcaseが注入executorへ渡ることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: module, probe case, evidence, またはpass診断が変化した場合.
    """
    fake_osu_module = object()
    observed_case: GetscoresProbeCase | None = None
    observed_osu_module: object | None = None

    def import_osu() -> object:
        """あらかじめ用意したosu.py module objectを返す.

        Returns:
            object: 注入executorへ渡すfake osu.py module.
        """
        return fake_osu_module

    def executor(osu_module: object, case: GetscoresProbeCase) -> SurfaceResult:
        """受信したmoduleとcaseを記録してpass結果を返す.

        Args:
            osu_module (object): import関数が返したfake osu.py module.
            case (GetscoresProbeCase): 注入executorが受け取るgetscores probe case.

        Returns:
            SurfaceResult: injected executorの成功を表すoptional pass結果.
        """
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
    """注入executorのerrorがoptional unavailable結果へ変換されることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: executor errorのstatus, run failure, または診断typeが変化した場合.
    """

    def executor(osu_module: object, case: GetscoresProbeCase) -> SurfaceResult:
        """Local client失敗を再現するためexecutor errorを送出する.

        Args:
            osu_module (object): testでは使用しないfake osu.py module.
            case (GetscoresProbeCase): testでは使用しないgetscores probe case.

        Raises:
            RuntimeError: local client failureを再現するため常に送出する.
        """
        _ = (osu_module, case)
        raise RuntimeError("local client failed")

    probe = OsuPyProbe(import_osu=object, executor=executor)

    result = probe.probe_getscores(_probe_case(), _ready_prerequisites())

    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.fails_run is False
    assert result.diagnostic_summary.message == ("osu.py getscores probe failed: RuntimeError")


def _probe_case() -> GetscoresProbeCase:
    """target不要のosu.py probeで使う固定getscores caseを生成する.

    Returns:
        GetscoresProbeCase: checksumとlegacy request fieldを持つtest用case.
    """
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
    """すべてのosu.py probe前提を満たすtest用inputを生成する.

    Returns:
        OsuPyProbePrerequisites: version, executable SHA-256, credential可用性を持つinput.
    """
    return OsuPyProbePrerequisites(
        version="20260217",
        executable_sha256="0" * 64,
        credentials_present=True,
    )


def _pass_result(message: str) -> SurfaceResult:
    """Optional osu.py probe用の成功surface結果を生成する.

    Args:
        message (str): reportへ出力するtest用診断message.

    Returns:
        SurfaceResult: HEADLESS_PROBEかつOPTIONAL scopeのpass結果.
    """
    return SurfaceResult(
        surface=StableSurface.GETSCORES,
        status=VerificationStatus.PASS,
        evidence_type=EvidenceType.HEADLESS_PROBE,
        scope=EvidenceScope.OPTIONAL,
        diagnostic_summary=DiagnosticSummary(message=message),
        reference="optional:osu.py getscores probe",
    )
