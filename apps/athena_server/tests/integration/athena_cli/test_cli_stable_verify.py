"""dev stable-verify CLIの入力制約と可視report contractを統合検証する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, override

from typer.testing import CliRunner

from athena_cli.commands import dev as dev_command
from athena_cli.main import app
from athena_cli.stable_verification.client import ProbeResponse
from athena_cli.stable_verification.getscores import GetscoresVerifier
from athena_cli.stable_verification.models import (
    DiagnosticSummary,
    EvidenceScope,
    EvidenceType,
    GetscoresProbeCase,
    StableSurface,
    StableTarget,
    SurfaceResult,
    VerificationRunResult,
    VerificationStatus,
)
from athena_cli.stable_verification.runner import VerificationRunRequest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import pytest


runner = CliRunner()


@dataclass(frozen=True, slots=True)
class FakeRoutingConfig:
    """host未指定時のrouting設定を再現するtest doubleを表す.

    Attributes:
        domain (str): stable host identityとして返すrouting domain.
    """

    domain: str = "config-domain.test"


@dataclass(slots=True)
class RecordingRunner:
    """stable verify CLIが渡すrequestを記録するtest runnerを表す.

    Attributes:
        result (VerificationRunResult): run呼出しごとに返す固定結果.
        requests (list[VerificationRunRequest]): CLIから受け取った実行requestの順序付き記録.
    """

    result: VerificationRunResult
    requests: list[VerificationRunRequest]

    def __init__(self, result: VerificationRunResult) -> None:
        """固定resultを返す記録runnerを初期化する.

        Args:
            result (VerificationRunResult): runごとに返すtest用verification結果.
        """
        self.result = result
        self.requests = []

    def run(self, request: VerificationRunRequest) -> VerificationRunResult:
        """requestを記録して固定のverification結果を返す.

        Args:
            request (VerificationRunRequest): CLIが構築したtargetとsurface指定を含むrequest.

        Returns:
            VerificationRunResult: constructorで指定した固定結果.
        """
        self.requests.append(request)
        return self.result


def test_stable_verify_rejects_production_before_config_or_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """production指定がconfig読込とrunner生成より先に拒否されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): CLI依存関数をfail-fastなtest doubleへ置換するfixture.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: production拒否前にconfigまたはrunnerへ到達するかerror出力が変化した場合.
    """

    def forbidden_load_routing_config() -> FakeRoutingConfig:
        """config読込が早過ぎる場合にtestを失敗させる.

        Raises:
            AssertionError: production拒否より先にrouting configを読んだ場合.
        """
        raise AssertionError("production rejection must happen before config loading")

    def forbidden_create_runner(target: StableTarget) -> RecordingRunner:
        """runner生成が早過ぎる場合にtestを失敗させる.

        Args:
            target (StableTarget): CLIが生成しようとしたstable target. testでは使用しない.

        Raises:
            AssertionError: production拒否より先にrunnerを生成した場合.
        """
        _ = target
        raise AssertionError("production rejection must happen before runner creation")

    monkeypatch.setattr(dev_command, "load_routing_config", forbidden_load_routing_config)
    monkeypatch.setattr(
        dev_command,
        "create_stable_verification_runner",
        forbidden_create_runner,
    )

    result = runner.invoke(
        app,
        ["dev", "stable-verify", "--env", "production"],
    )

    assert result.exit_code != 0
    assert "only available for development and test" in result.output


def test_stable_verify_requires_base_url_before_config_or_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Base URL未指定がconfig読込とrunner生成より先に拒否されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): CLI依存関数をfail-fastなtest doubleへ置換するfixture.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: base URL拒否前にconfigまたはrunnerへ到達するかerror出力が変化した場合.
    """

    def forbidden_load_routing_config() -> FakeRoutingConfig:
        """config読込が早過ぎる場合にtestを失敗させる.

        Raises:
            AssertionError: base URL validationより先にrouting configを読んだ場合.
        """
        raise AssertionError("missing base-url must fail before config loading")

    def forbidden_create_runner(target: StableTarget) -> RecordingRunner:
        """runner生成が早過ぎる場合にtestを失敗させる.

        Args:
            target (StableTarget): CLIが生成しようとしたstable target. testでは使用しない.

        Raises:
            AssertionError: base URL validationより先にrunnerを生成した場合.
        """
        _ = target
        raise AssertionError("missing base-url must fail before runner creation")

    monkeypatch.setattr(dev_command, "load_routing_config", forbidden_load_routing_config)
    monkeypatch.setattr(
        dev_command,
        "create_stable_verification_runner",
        forbidden_create_runner,
    )

    result = runner.invoke(
        app,
        ["dev", "stable-verify", "--env", "test"],
    )

    assert result.exit_code != 0
    assert "--base-url is required" in result.output


def test_stable_verify_uses_host_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """明示hostがtarget host identityとtext reportへそのまま反映されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): runner factoryを記録runnerへ置換するfixture.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: target field, selected surface, またはStable Host出力が変化した場合.
    """
    recording_runner = RecordingRunner(_run_result(host_identity="override.test"))

    monkeypatch.setattr(
        dev_command,
        "create_stable_verification_runner",
        _runner_factory(recording_runner),
    )

    result = runner.invoke(
        app,
        [
            "dev",
            "stable-verify",
            "--env",
            "test",
            "--base-url",
            "http://127.0.0.1:8000",
            "--host",
            "override.test",
            "--surface",
            "getscores",
        ],
    )

    assert result.exit_code == 0
    assert recording_runner.requests[0].target == StableTarget(
        base_url="http://127.0.0.1:8000",
        host_identity="override.test",
        timeout_seconds=2.0,
    )
    assert recording_runner.requests[0].surfaces == (StableSurface.GETSCORES,)
    assert "Stable Host: osu.override.test" in result.output


def test_stable_verify_uses_routing_domain_when_host_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """host未指定時にrouting configのdomainがtargetへ採用されることを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): routing configとrunner factoryをtest doubleへ
            置換するfixture.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: host未指定時のtarget host identityがrouting domainと異なる場合.
    """
    recording_runner = RecordingRunner(_run_result(host_identity="config-domain.test"))

    monkeypatch.setattr(
        dev_command,
        "load_routing_config",
        lambda: FakeRoutingConfig(domain="config-domain.test"),
    )
    monkeypatch.setattr(
        dev_command,
        "create_stable_verification_runner",
        _runner_factory(recording_runner),
    )

    result = runner.invoke(
        app,
        [
            "dev",
            "stable-verify",
            "--env",
            "test",
            "--base-url",
            "http://127.0.0.1:8000",
            "--surface",
            "getscores",
        ],
    )

    assert result.exit_code == 0
    assert recording_runner.requests[0].target is not None
    assert recording_runner.requests[0].target.host_identity == "config-domain.test"


def test_stable_verify_reports_unavailable_local_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional local target unavailableがsuccess exitと可視診断を保つことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): runner factoryをunavailable結果を返すtest doubleへ
            置換するfixture.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: optional unavailableのexit codeまたはtext reportが変化した場合.
    """
    recording_runner = RecordingRunner(
        _run_result(
            host_identity="athena.localhost",
            status=VerificationStatus.UNAVAILABLE,
            diagnostic="GET /web/osu-osz2-getscores.php unavailable",
        )
    )

    monkeypatch.setattr(
        dev_command,
        "create_stable_verification_runner",
        _runner_factory(recording_runner),
    )

    result = runner.invoke(
        app,
        [
            "dev",
            "stable-verify",
            "--env",
            "test",
            "--base-url",
            "http://127.0.0.1:9",
            "--host",
            "athena.localhost",
            "--surface",
            "getscores",
        ],
    )

    assert result.exit_code == 0
    assert "getscores unavailable headless_probe optional" in result.output
    assert "GET /web/osu-osz2-getscores.php unavailable" in result.output


def test_getscores_executor_checks_completion_evidence_without_target() -> None:
    """target未設定でもmandatory completion evidenceを検証する.

    Returns:
        None: Completion fixture結果とoptional probe skipを検証する.

    Raises:
        AssertionError: mandatory evidenceが欠落するかoptional probeの扱いが変わる場合.
    """
    verification_runner = dev_command.create_stable_verification_runner(None)
    result = verification_runner.run(
        VerificationRunRequest(
            target=None,
            surfaces=(StableSurface.GETSCORES,),
            require_target=False,
        )
    )
    results = result.results

    completion_results = tuple(
        result
        for result in results
        if result.reference is not None and result.reference.startswith("getscores completion ")
    )
    assert [(result.reference, result.status, result.scope) for result in completion_results] == [
        (
            "getscores completion response shapes",
            VerificationStatus.PASS,
            EvidenceScope.MANDATORY,
        ),
        (
            "getscores completion branch cases",
            VerificationStatus.PASS,
            EvidenceScope.MANDATORY,
        ),
        (
            "getscores completion status crosswalk",
            VerificationStatus.PASS,
            EvidenceScope.MANDATORY,
        ),
    ]
    assert results[-1].status is VerificationStatus.SKIP
    assert results[-1].scope is EvidenceScope.OPTIONAL
    assert results[-1].diagnostic_summary.message == (
        "getscores local probe skipped: target not configured"
    )


def test_stable_verify_enumerates_completion_evidence_before_optional_target_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLIがcompletion evidenceをoptional target probeより先に列挙することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): Getscores verifierをrecording test doubleへ
            差し替えるfixture.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: CLI outputに3つのcompletion resultがない, またはtarget probe条件が
            変わる場合.

    Notes:
        target probeはfixture結果の後も一度だけoptional evidenceとして実行される.
    """
    _RecordingGetscoresVerifier.target_probe_calls = 0
    monkeypatch.setattr(
        dev_command,
        "GetscoresVerifier",
        _RecordingGetscoresVerifier,
    )

    result = runner.invoke(
        app,
        [
            "dev",
            "stable-verify",
            "--env",
            "test",
            "--base-url",
            "http://127.0.0.1:8000",
            "--host",
            "athena.localhost",
            "--surface",
            "getscores",
        ],
    )

    assert result.exit_code == 0
    assert _RecordingGetscoresVerifier.target_probe_calls == 1
    assert (
        "getscores pass golden_fixture mandatory getscores response shapes validation passed"
    ) in result.output
    assert (
        "getscores pass golden_fixture mandatory getscores branch cases validation passed"
    ) in result.output
    assert (
        "getscores pass golden_fixture mandatory getscores status crosswalk validation passed"
    ) in result.output
    assert (
        "getscores pass headless_probe optional "
        "getscores response parsed as header empty leaderboard"
    ) in result.output


def test_stable_verify_replay_download_surface_is_known_gap() -> None:
    """Replay downloadがlive probe未設定のknown gapとして表示されることを検証する.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: exit code, optional skip行, またはlive probe診断が変化した場合.
    """
    result = runner.invoke(
        app,
        [
            "dev",
            "stable-verify",
            "--env",
            "test",
            "--base-url",
            "http://127.0.0.1:8000",
            "--host",
            "athena.localhost",
            "--surface",
            "replay_download",
        ],
    )

    assert result.exit_code == 0
    assert "replay_download skip headless_probe optional" in result.output
    assert "stable-verify live probe is not configured" in result.output


def test_stable_verify_json_output_contains_surface_result_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON optionがsurface result schemaの各fieldを可視出力することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): runner factoryを固定結果を返すtest doubleへ
            置換するfixture.

    Returns:
        None: Assertionだけを実行する.

    Raises:
        AssertionError: JSON outputのsurface, status, evidence, scope, またはdiagnostic fieldが
            変化した場合.
    """
    recording_runner = RecordingRunner(_run_result(host_identity="athena.localhost"))

    monkeypatch.setattr(
        dev_command,
        "create_stable_verification_runner",
        _runner_factory(recording_runner),
    )

    result = runner.invoke(
        app,
        [
            "dev",
            "stable-verify",
            "--env",
            "test",
            "--base-url",
            "http://127.0.0.1:8000",
            "--host",
            "athena.localhost",
            "--surface",
            "getscores",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"surface": "getscores"' in result.output
    assert '"status": "pass"' in result.output
    assert '"evidence_type": "headless_probe"' in result.output
    assert '"scope": "optional"' in result.output
    assert '"diagnostic_summary": "local probe parsed"' in result.output


def _run_result(
    *,
    host_identity: str,
    status: VerificationStatus = VerificationStatus.PASS,
    diagnostic: str = "local probe parsed",
) -> VerificationRunResult:
    """CLI testで返す1件のoptional getscores resultを生成する.

    Args:
        host_identity (str): generated targetのstable host identity.
        status (VerificationStatus): generated surface resultのverification status.
        diagnostic (str): generated surface resultのreport-safe診断message.

    Returns:
        VerificationRunResult: optional HEADLESS_PROBE getscores結果を1件含むrun.
    """
    return VerificationRunResult(
        target=StableTarget(
            base_url="http://127.0.0.1:8000",
            host_identity=host_identity,
            timeout_seconds=2.0,
        ),
        results=(
            SurfaceResult(
                surface=StableSurface.GETSCORES,
                status=status,
                evidence_type=EvidenceType.HEADLESS_PROBE,
                scope=EvidenceScope.OPTIONAL,
                diagnostic_summary=DiagnosticSummary(message=diagnostic),
                reference="local getscores probe",
            ),
        ),
    )


def _runner_factory(
    recording_runner: RecordingRunner,
) -> Callable[[StableTarget], RecordingRunner]:
    """常に同じ記録runnerを返すCLI runner factoryを生成する.

    Args:
        recording_runner (RecordingRunner): factory呼出しごとに返すrecording runner.

    Returns:
        Callable[[StableTarget], RecordingRunner]: targetを受け取り同じrunnerを返すfactory.
    """

    def create_runner(target: StableTarget) -> RecordingRunner:
        """targetを使用せず設定済みのrecording runnerを返す.

        Args:
            target (StableTarget): CLIが構築したstable target. testでは使用しない.

        Returns:
            RecordingRunner: factory外側で指定したrecording runner.
        """
        _ = target
        return recording_runner

    return create_runner


@dataclass(frozen=True, slots=True)
class _FixtureProbeClient:
    """固定getscores responseを返すGetscoresVerifier用client fakeを表す.

    Attributes:
        target (StableTarget): fakeが接続先として受け取るstable target.
    """

    target: StableTarget

    def get_web_legacy(
        self,
        path: str,
        *,
        query: Mapping[str, str],
        host_prefix: str = "osu",
    ) -> ProbeResponse:
        """request内容を使わずranked fixture相当のprobe responseを返す.

        Args:
            path (str): getscores legacy endpoint path. testでは使用しない.
            query (Mapping[str, str]): getscores query field群. testでは使用しない.
            host_prefix (str): Host headerのprefix. testでは使用しない.

        Returns:
            ProbeResponse: empty leaderboard headerを含む成功response.
        """
        _ = (path, query, host_prefix)
        return ProbeResponse(
            status=VerificationStatus.PASS,
            body=(b"2|false|75|1|0||\n0\n[bold:0,size:20]Artist|Title\n10\n"),
            diagnostic_summary=DiagnosticSummary(
                message="fixture target response",
                method="GET",
                path="/web/osu-osz2-getscores.php",
                status_code=200,
                response_byte_size=51,
            ),
        )


class _RecordingGetscoresVerifier(GetscoresVerifier[object]):
    """target probe呼出し回数を記録するGetscoresVerifier test doubleを表す.

    Attributes:
        target_probe_calls (ClassVar[int]): probe_targetを実行した回数.
    """

    target_probe_calls: ClassVar[int] = 0

    def __init__(self, *, target: StableTarget) -> None:
        """Fixture probe clientを使うverifierを初期化する.

        Args:
            target (StableTarget): base verifierとfixture clientが使用するstable target.
        """
        super().__init__(target=target, client=_FixtureProbeClient(target))

    @override
    def probe_target(self, case: GetscoresProbeCase) -> SurfaceResult:
        """呼出し回数を増やしてbase verifierのtarget probeを実行する.

        Args:
            case (GetscoresProbeCase): target probeに渡すgetscores request case.

        Returns:
            SurfaceResult: base verifierがfixture clientから生成したprobe結果.
        """
        _RecordingGetscoresVerifier.target_probe_calls += 1
        return super().probe_target(case)
