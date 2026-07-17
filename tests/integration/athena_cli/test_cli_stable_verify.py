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

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import pytest

    from athena_cli.stable_verification.runner import VerificationRunRequest


runner = CliRunner()


@dataclass(frozen=True, slots=True)
class FakeRoutingConfig:
    domain: str = "config-domain.test"


@dataclass(slots=True)
class RecordingRunner:
    result: VerificationRunResult
    requests: list[VerificationRunRequest]

    def __init__(self, result: VerificationRunResult) -> None:
        self.result = result
        self.requests = []

    def run(self, request: VerificationRunRequest) -> VerificationRunResult:
        self.requests.append(request)
        return self.result


def test_stable_verify_rejects_production_before_config_or_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_load_routing_config() -> FakeRoutingConfig:
        raise AssertionError("production rejection must happen before config loading")

    def forbidden_create_runner(target: StableTarget) -> RecordingRunner:
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
    def forbidden_load_routing_config() -> FakeRoutingConfig:
        raise AssertionError("missing base-url must fail before config loading")

    def forbidden_create_runner(target: StableTarget) -> RecordingRunner:
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


def test_stable_verify_enumerates_completion_evidence_before_optional_target_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLIがcompletion evidenceと既存optional target probeを順に列挙することを検証する。

    Args:
        monkeypatch (pytest.MonkeyPatch): Getscores verifierをrecording test doubleへ
            差し替えるfixture。

    Returns:
        None: Assertionだけを実行する。

    Raises:
        AssertionError: CLI outputに3つのcompletion resultがない, またはtarget probe条件が
            変わる場合。

    Notes:
        Target probeはfixture結果の後も一度だけoptional evidenceとして実行される。
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
    def create_runner(target: StableTarget) -> RecordingRunner:
        _ = target
        return recording_runner

    return create_runner


@dataclass(frozen=True, slots=True)
class _FixtureProbeClient:
    target: StableTarget

    def get_web_legacy(
        self,
        path: str,
        *,
        query: Mapping[str, str],
        host_prefix: str = "osu",
    ) -> ProbeResponse:
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
    target_probe_calls: ClassVar[int] = 0

    def __init__(self, *, target: StableTarget) -> None:
        super().__init__(target=target, client=_FixtureProbeClient(target))

    @override
    def probe_target(self, case: GetscoresProbeCase) -> SurfaceResult:
        _RecordingGetscoresVerifier.target_probe_calls += 1
        return super().probe_target(case)
