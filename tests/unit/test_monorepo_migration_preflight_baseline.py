"""monorepo移行前baselineの再検証契約を検証する."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import tools.monorepo_migration.verify_preflight_baseline as preflight_baseline
from tools.monorepo_migration.verify_preflight_baseline import (
    Baseline,
    VerificationMode,
    check_kiro_and_todo_inventory,
    collect_alembic_current_difference,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

REPOSITORY_ROOT = Path(__file__).parents[2]
BASELINE_PATH = REPOSITORY_ROOT / ".kiro/specs/monorepo-migration/preflight-baseline.json"
VERIFIER_PATH = REPOSITORY_ROOT / "tools/monorepo_migration/verify_preflight_baseline.py"


def _load_baseline_document() -> dict[str, object]:
    """checked-in baselineをtestで安全に変更できるmappingとして読み込む.

    Returns:
        dict[str, object]: JSON objectとして検証済みのbaseline document.

    Raises:
        TypeError: baselineがstring keyを持つJSON objectではない場合.
    """
    decoded = cast("object", json.loads(BASELINE_PATH.read_text(encoding="utf-8")))
    return _mapping_value(decoded, "baseline")


def _mapping_value(value: object, context: str) -> dict[str, object]:
    """JSON objectを独立して変更できるstring key mappingへ変換する.

    Args:
        value (object): JSON objectである必要がある値.
        context (str): type errorへ含めるfieldの用途.

    Returns:
        dict[str, object]: 独立して変更できるstring key mapping.

    Raises:
        TypeError: valueがstring keyを持つJSON objectではない場合.
    """
    if not isinstance(value, dict):
        raise TypeError(f"{context} must be a JSON object")

    source = cast("Mapping[object, object]", value)
    mapping: dict[str, object] = {}
    for key, nested_value in source.items():
        if not isinstance(key, str):
            raise TypeError(f"{context} keys must be strings")
        mapping[key] = nested_value
    return mapping


def _nested_mapping(document: dict[str, object], key: str) -> dict[str, object]:
    """documentのobject fieldをcopyして取得する.

    Args:
        document (dict[str, object]): 参照するJSON object.
        key (str): objectである必要があるfield名.

    Returns:
        dict[str, object]: fieldの独立したstring key mapping.
    """
    return _mapping_value(document[key], key)


def _string_list_value(document: dict[str, object], key: str) -> list[str]:
    """documentのstring array fieldをcopyして取得する.

    Args:
        document (dict[str, object]): 参照するJSON object.
        key (str): string arrayである必要があるfield名.

    Returns:
        list[str]: fieldの独立したstring value list.

    Raises:
        TypeError: fieldがstringだけからなるJSON arrayではない場合.
    """
    value = document[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a JSON array")

    strings: list[str] = []
    for item in cast("list[object]", value):
        if not isinstance(item, str):
            raise TypeError(f"{key} must contain only strings")
        strings.append(item)
    return strings


def _write_mutated_baseline(tmp_path: Path, baseline: dict[str, object]) -> Path:
    """一時directoryへ変更済みbaseline JSONを書き込む.

    Args:
        tmp_path (Path): mutationを隔離する一時directory.
        baseline (dict[str, object]): JSONとして保存する変更済みbaseline.

    Returns:
        Path: checkerへ渡す変更済みbaseline file path.
    """
    path = tmp_path / "preflight-baseline.json"
    _ = path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    return path


def _successful_alembic_current(_: Path) -> subprocess.CompletedProcess[str]:
    """記録済みheadを含むAlembic current command成功resultを返す.

    Args:
        _ (Path): fake commandが実行対象として受け取るrepository root.

    Returns:
        subprocess.CompletedProcess[str]: head revisionを標準出力に含む成功result.
    """
    return subprocess.CompletedProcess(
        args=["uv", "run", "alembic", "current"],
        returncode=0,
        stdout="20260713_0700 (head)\n",
        stderr="",
    )


def _alembic_current_runner_with_output(
    output: str,
) -> Callable[[Path], subprocess.CompletedProcess[str]]:
    """指定した標準出力を返すAlembic current runnerを作る.

    Args:
        output (str): fake Alembic current commandが返す標準出力.

    Returns:
        Callable[[Path], subprocess.CompletedProcess[str]]: repository rootを受け取り、指定出力で
            成功するfake runner.
    """

    def run_current(_: Path) -> subprocess.CompletedProcess[str]:
        """指定済みのAlembic current標準出力を成功resultとして返す.

        Args:
            _ (Path): fake commandが実行対象として受け取るrepository root.

        Returns:
            subprocess.CompletedProcess[str]: 指定された標準出力を含む成功result.
        """
        return subprocess.CompletedProcess(
            args=["uv", "run", "alembic", "current"],
            returncode=0,
            stdout=output,
            stderr="",
        )

    return run_current


def _run_checker(
    baseline_path: Path,
    *,
    alembic_current: bool = False,
    environment: dict[str, str] | None = None,
    mode: str | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> subprocess.CompletedProcess[str]:
    """指定baselineに対するchecker CLIをsubprocessで実行する.

    Args:
        baseline_path (Path): checkerへ渡すbaseline JSON file.
        alembic_current (bool): Alembic current checkも実行するか.
        environment (dict[str, str] | None): child processへ渡す環境変数. Noneなら継承する.
        mode (str | None): verifierへ渡すphysical layout mode. NoneならCLI既定値を使う.
        repository_root (Path): checkerを実行する検証対象repository root.

    Returns:
        subprocess.CompletedProcess[str]: stdout、stderr、終了codeを含むchecker実行結果.
    """
    command = [
        sys.executable,
        str(VERIFIER_PATH),
        "--baseline",
        str(baseline_path),
    ]
    if mode is not None:
        command.extend(["--mode", mode])
    if alembic_current:
        command.append("--alembic-current")
    return subprocess.run(
        command,
        cwd=repository_root,
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=30,
    )


def _make_post_cutover_repository(tmp_path: Path) -> Path:
    """予定済みのserver/crypto relocationだけを再現するtemporary repositoryを作る.

    旧root source、Alembic、legacy script、root task gatewayを作らず、Task 1.1のpost-cutover
    compatibility modeがowner workspaceから意味的contractを検証できるかを確認するfixtureである.

    Args:
        tmp_path (Path): fixture repositoryを作成する一時directory.

    Returns:
        Path: `apps/athena_server`と`packages/athena_crypto`を含むrepository root.
    """
    server_root = tmp_path / "apps/athena_server"
    crypto_root = tmp_path / "packages/athena_crypto"
    ignored_paths = shutil.ignore_patterns("__pycache__", ".pytest_cache", "target")
    _ = shutil.copytree(
        REPOSITORY_ROOT / "src/osu_server", server_root / "src/osu_server", ignore=ignored_paths
    )
    _ = shutil.copytree(
        REPOSITORY_ROOT / "src/athena_cli", server_root / "src/athena_cli", ignore=ignored_paths
    )
    _ = shutil.copytree(REPOSITORY_ROOT / "alembic", server_root / "alembic", ignore=ignored_paths)
    _ = shutil.copytree(REPOSITORY_ROOT / "athena-crypto", crypto_root, ignore=ignored_paths)
    _ = shutil.copy2(REPOSITORY_ROOT / "pyproject.toml", server_root / "pyproject.toml")
    _ = shutil.copy2(REPOSITORY_ROOT / "alembic.ini", server_root / "alembic.ini")
    _ = shutil.copy2(REPOSITORY_ROOT / ".gitignore", tmp_path / ".gitignore")
    _ = shutil.copy2(REPOSITORY_ROOT / "process-compose.yml", tmp_path / "process-compose.yml")
    _ = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return tmp_path


def test_preflight_baseline_matches_current_repository_contract() -> None:
    """移行前snapshotが現在のruntimeとcleanup inventoryを機械的に検証する契約を確認する.

    source treeを移動する前にcheckerを実行し、runtime namespace、entrypoint、task名、CLI、
    Alembic、build、quality/test対象、cleanup inventoryの差分がないことを確認する.

    Returns:
        None: checkerの成功終了を検証して完了し、呼び出し側へ値を返さない.
    """
    result = _run_checker(BASELINE_PATH)

    assert result.returncode == 0, result.stderr
    assert "Alembic current was not checked." in result.stdout


def test_post_cutover_mode_accepts_relocated_contract_without_pre_cutover_inventory(
    tmp_path: Path,
) -> None:
    """Post-cutover modeが予定済みrelocation後も意味的contractを比較することを検証する.

    旧root source、Alembic、manifest、legacy script、root task gatewayを持たないfixtureに対して
    post-cutover modeが成功し、同じtreeをpre-cutover modeで検証した場合はinventory mismatchに
    なることを確認する.

    Args:
        tmp_path (Path): relocation済みfixtureを隔離する一時directory.

    Returns:
        None: 物理pathのpreflight inventoryと意味的compatibility modeの分離を検証する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    assert not (repository_root / "justfile").exists()

    post_cutover_result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )
    pre_cutover_result = _run_checker(
        BASELINE_PATH,
        mode="pre-cutover",
        repository_root=repository_root,
    )

    assert post_cutover_result.returncode == 0, post_cutover_result.stderr
    assert pre_cutover_result.returncode != 0
    assert "Baseline verification could not complete" not in pre_cutover_result.stderr
    assert "Required baseline path is missing" in pre_cutover_result.stderr
    assert "Pre-cutover cleanup inventory path is missing" in pre_cutover_result.stderr


def test_post_cutover_mode_preserves_exact_alembic_current_contract(tmp_path: Path) -> None:
    """Post-cutover modeもrecorded headと完全一致する単一currentだけを許可することを検証する.

    予定済みowner workspaceだけを持つfixtureにfake Alembic current runnerを注入し、pre-cutover
    modeと同じsingle revisionの完全一致判定を使うことを確認する.

    Args:
        tmp_path (Path): relocation済みfixtureを隔離する一時directory.

    Returns:
        None: post-cutoverのAlembic current比較が差分なしで完了することを検証する.
    """
    differences = collect_alembic_current_difference(
        _make_post_cutover_repository(tmp_path),
        Baseline(document=_load_baseline_document()),
        mode=VerificationMode.POST_CUTOVER,
        run_current=_successful_alembic_current,
    )

    assert differences == []


def test_post_cutover_alembic_current_runs_from_server_workspace(tmp_path: Path) -> None:
    """Post-cutoverのAlembic currentをserver owner rootから実行することを検証する.

    Relocation済みrepositoryへrunnerを注入し、rootではなくbaselineがrecordした
    `apps/athena_server`がAlembic commandのcurrent working directoryになることを確認する.

    Args:
        tmp_path (Path): relocation済みfixtureを隔離する一時directory.

    Returns:
        None: runnerが受け取ったserver workspace pathを検証して完了する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    runner_roots: list[Path] = []

    def run_current(command_root: Path) -> subprocess.CompletedProcess[str]:
        """Alembic commandのworking directoryを記録してhead成功resultを返す.

        Args:
            command_root (Path): checkerがAlembic commandへ渡したworking directory.

        Returns:
            subprocess.CompletedProcess[str]: 記録済みheadを含む成功result.
        """
        runner_roots.append(command_root)
        return _successful_alembic_current(command_root)

    differences = collect_alembic_current_difference(
        repository_root,
        Baseline(document=_load_baseline_document()),
        mode=VerificationMode.POST_CUTOVER,
        run_current=run_current,
    )

    assert differences == []
    assert runner_roots == [repository_root / "apps/athena_server"]


def test_alembic_current_cli_forwards_post_cutover_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--alembic-current`がCLIで選択したpost-cutover modeをcollectorへ渡すことを検証する.

    CLI parsing、通常contract検証、Alembic current collectorを隔離し、post-cutover modeが
    optional current checkまで変更されずに到達することを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): module dependencyをin-memory fakeへ置換するfixture.

    Returns:
        None: Alembic collectorがpost-cutover modeを受け取ったことを検証して完了する.
    """
    baseline = Baseline(document=_load_baseline_document())
    collected_modes: list[VerificationMode] = []

    def parse_arguments() -> preflight_baseline.ParsedArguments:
        """Post-cutover Alembic currentを指定したCLI引数を返す.

        Returns:
            ParsedArguments: current checkを有効化したpost-cutover CLI引数.
        """
        return preflight_baseline.ParsedArguments(
            baseline=BASELINE_PATH,
            alembic_current=True,
            mode=VerificationMode.POST_CUTOVER,
        )

    def load_baseline(_: Path) -> Baseline:
        """既知のbaselineを返す.

        Args:
            _ (Path): checkerが読み込もうとしたbaseline path.

        Returns:
            Baseline: test用に読み込んだbaseline.
        """
        return baseline

    def collect_differences(
        _: Path,
        __: Baseline,
        *,
        mode: VerificationMode,
    ) -> list[str]:
        """通常のchecker差分を発生させない.

        Args:
            _ (Path): checkerが検証対象として渡したrepository root.
            __ (Baseline): checkerが使用するbaseline.
            mode (VerificationMode): CLIから通常checkerへ渡されたlayout mode.

        Returns:
            list[str]: 通常contractが一致したことを表す空list.
        """
        assert __ is baseline
        assert mode is VerificationMode.POST_CUTOVER
        return []

    def collect_current_difference(
        _: Path,
        __: Baseline,
        *,
        mode: VerificationMode = VerificationMode.PRE_CUTOVER,
        run_current: Callable[[Path], subprocess.CompletedProcess[str]] | None = None,
    ) -> list[str]:
        """Alembic current collectorへ渡されたmodeを記録する.

        Args:
            _ (Path): checkerが検証対象として渡したrepository root.
            __ (Baseline): checkerが使用するbaseline.
            mode (VerificationMode): optional Alembic current checkへ渡されたlayout mode.
            run_current (Callable[[Path], subprocess.CompletedProcess[str]] | None): injected
                Alembic runner. CLI呼び出しではNone.

        Returns:
            list[str]: Alembic currentが一致したことを表す空list.
        """
        assert __ is baseline
        assert run_current is None
        collected_modes.append(mode)
        return []

    monkeypatch.setattr(preflight_baseline, "_parse_arguments", parse_arguments)
    monkeypatch.setattr(preflight_baseline, "_load_baseline", load_baseline)
    monkeypatch.setattr(preflight_baseline, "_collect_differences", collect_differences)
    monkeypatch.setattr(
        preflight_baseline,
        "collect_alembic_current_difference",
        collect_current_difference,
    )

    preflight_baseline.main()

    assert collected_modes == [VerificationMode.POST_CUTOVER]


def test_post_cutover_alembic_current_on_pre_cutover_tree_reports_mismatches() -> None:
    """移行前treeのpost-cutover Alembic currentを診断可能なmismatchとして返すことを検証する.

    旧root layoutから`--mode post-cutover --alembic-current`を実行し、relocation不足と
    server workspace不足をouter CLI errorではなく同じbaseline mismatch reportへ収集することを
    確認する.

    Returns:
        None: physical layoutとAlembic command rootの差分がstderrへ報告されることを検証して
            完了する.
    """
    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        alembic_current=True,
    )

    assert result.returncode != 0
    assert "BASELINE MISMATCH: Post-cutover relocation target is missing" in result.stderr
    assert "BASELINE MISMATCH: Alembic current command root is missing" in result.stderr
    assert "Baseline verification could not complete" not in result.stderr


def test_alembic_current_runner_oserror_is_reported_as_mismatch() -> None:
    """Alembic runnerのOS errorをbaseline mismatchへ変換することを検証する.

    実行可能なpre-cutover rootへOS errorを送出するrunnerを注入し、runner failureがchecker全体の
    例外ではなくoperatorが対処可能なAlembic current差分になることを確認する.

    Returns:
        None: runner OS errorを表すAlembic current mismatchを検証して完了する.
    """

    def run_current(_: Path) -> subprocess.CompletedProcess[str]:
        """Alembic subprocessを起動できない状態を再現する.

        Args:
            _ (Path): checkerがAlembic commandへ渡したworking directory.

        Raises:
            FileNotFoundError: injected Alembic runnerが利用できない場合.
        """
        raise FileNotFoundError("injected Alembic runner is unavailable")

    differences = collect_alembic_current_difference(
        REPOSITORY_ROOT,
        Baseline(document=_load_baseline_document()),
        run_current=run_current,
    )

    assert len(differences) == 1
    assert "Alembic current check could not run" in differences[0]
    assert "injected Alembic runner is unavailable" in differences[0]


def test_preflight_baseline_uses_recorded_migration_head_for_alembic_current() -> None:
    """Alembic current比較がrecorded migration headを唯一のauthorityとして使うことを検証する.

    到達可能databaseを必要としないfake current commandを注入し、headだけを改ざんして、
    `current_at_head`が一致していてもcurrent revision mismatchが差分として返ることを確認する.

    Returns:
        None: Alembic current mismatchを検証し、呼び出し側へ値を返さずに完了する.
    """
    document = _load_baseline_document()
    migrations = _nested_mapping(document, "migrations")
    migrations["head"] = "incompatible-current-revision"
    document["migrations"] = migrations

    differences = collect_alembic_current_difference(
        REPOSITORY_ROOT,
        Baseline(document=document),
        run_current=_successful_alembic_current,
    )

    expected_difference = "Alembic current differs from recorded head {!r}: {!r}".format(
        "incompatible-current-revision",
        "20260713_0700",
    )
    assert differences == [expected_difference]


def test_preflight_baseline_rejects_divergent_recorded_current_at_head(tmp_path: Path) -> None:
    """記録済みcurrent_at_headがrecorded migration headと矛盾すると拒否することを検証する.

    Databaseへ接続しない通常checkerを使い、snapshot内のcurrent/head関係そのものが壊れた場合に
    immutable preflight baselineとしてnon-zeroになることを確認する.

    Args:
        tmp_path (Path): 改ざんしたbaselineを隔離して保存する一時directory.

    Returns:
        None: current_at_headとheadの不一致をmismatchとして検証して完了する.
    """
    document = _load_baseline_document()
    migrations = _nested_mapping(document, "migrations")
    migrations["current_at_head"] = "incompatible-recorded-current"
    document["migrations"] = migrations

    result = _run_checker(_write_mutated_baseline(tmp_path, document))

    assert result.returncode != 0
    assert "Recorded Alembic current_at_head differs from recorded head" in result.stderr


def test_preflight_baseline_accepts_exact_single_alembic_head() -> None:
    """Alembic currentがrecorded headと完全一致する単一revisionなら受理することを検証する.

    Returns:
        None: head revisionだけを含む標準出力がmismatchを生まないことを検証して完了する.
    """
    differences = collect_alembic_current_difference(
        REPOSITORY_ROOT,
        Baseline(document=_load_baseline_document()),
        run_current=_successful_alembic_current,
    )

    assert differences == []


@pytest.mark.parametrize(
    ("output", "actual_current"),
    [
        (
            "",
            None,
        ),
        (
            "20260713_0700 (head)\n20260713_0600 (head)\n",
            None,
        ),
        (
            "20260713_0700-suffix (head)\n",
            "20260713_0700-suffix",
        ),
        (
            "prefix-20260713_0700 (head)\n",
            "prefix-20260713_0700",
        ),
    ],
)
def test_preflight_baseline_rejects_ambiguous_or_partial_alembic_current_output(
    output: str,
    actual_current: str | None,
) -> None:
    """Alembic currentの空、複数、prefix、substring出力を拒否することを検証する.

    Args:
        output (str): fake Alembic current commandが返す不正または曖昧な標準出力.
        actual_current (str | None): 出力から一意に取得できる不正revision. 空または複数時はNone.

    Returns:
        None: current revisionを一意かつ完全一致で識別できない出力の拒否を検証して完了する.
    """
    differences = collect_alembic_current_difference(
        REPOSITORY_ROOT,
        Baseline(document=_load_baseline_document()),
        run_current=_alembic_current_runner_with_output(output),
    )

    if actual_current is None:
        expected_difference = "Alembic current output must contain exactly one revision: " + repr(
            output.strip()
        )
    else:
        expected_difference = (
            "Alembic current differs from recorded head '20260713_0700': " + repr(actual_current)
        )

    assert differences == [expected_difference]


def _mutate_runtime_and_cli_contract(baseline: dict[str, object]) -> None:
    """RuntimeとCLI baselineのcurrent sourceと矛盾する値を作る.

    Args:
        baseline (dict[str, object]): testが変更するpreflight baseline document.

    Returns:
        None: runtimeとCLI categoryを改ざんし、呼び出し側へ値を返さずに完了する.
    """
    runtime = _nested_mapping(baseline, "runtime")
    namespaces = _nested_mapping(runtime, "python_namespaces")
    namespaces["incompatible_namespace"] = "pyproject.toml"
    runtime["python_namespaces"] = namespaces
    app = _nested_mapping(runtime, "app")
    app["invocation"] = "python -m incompatible_server"
    app["asgi_target"] = "incompatible_server.app:app"
    runtime["app"] = app
    worker = _nested_mapping(runtime, "worker")
    worker["entrypoint"] = "osu_server.worker:incompatible_broker"
    worker_task_names = _string_list_value(worker, "task_names")
    worker_task_names.append("baseline_only_worker_task")
    worker["task_names"] = worker_task_names
    runtime["worker"] = worker
    cli = _nested_mapping(runtime, "cli")
    cli["console_command"] = "incompatible-console-command"
    cli["console_entrypoint"] = "incompatible_cli.main:main"
    cli_command_groups = _string_list_value(cli, "command_groups")
    cli_command_groups.append("incompatible-command-group")
    cli["command_groups"] = cli_command_groups
    confirmation_contracts = _nested_mapping(cli, "confirmation_contract")
    env_confirmation = _nested_mapping(confirmation_contracts, "env_init_production_overwrite")
    confirmation_fragments = _string_list_value(env_confirmation, "fragments")
    confirmation_fragments[0] = "missing confirmation source evidence"
    env_confirmation["fragments"] = confirmation_fragments
    confirmation_contracts["env_init_production_overwrite"] = env_confirmation
    cli["confirmation_contract"] = confirmation_contracts
    exit_contracts = _nested_mapping(cli, "exit_contract")
    env_exit = _nested_mapping(exit_contracts, "env_expected_error_exit")
    exit_fragments = _string_list_value(env_exit, "fragments")
    exit_fragments[0] = "missing exit source evidence"
    env_exit["fragments"] = exit_fragments
    exit_contracts["env_expected_error_exit"] = env_exit
    cli["exit_contract"] = exit_contracts
    runtime["cli"] = cli
    baseline["runtime"] = runtime


def _mutate_build_and_validation_contract(baseline: dict[str, object]) -> None:
    """Buildとvalidation baselineのcurrent sourceと矛盾する値を作る.

    Args:
        baseline (dict[str, object]): testが変更するpreflight baseline document.

    Returns:
        None: buildとvalidation categoryを改ざんし、呼び出し側へ値を返さずに完了する.
    """
    builds = _nested_mapping(baseline, "builds")
    server_build = _nested_mapping(builds, "server")
    server_command = _string_list_value(server_build, "command")
    server_command[-1] = "incompatible-build"
    server_build["command"] = server_command
    server_build["distribution"] = "incompatible-server-distribution"
    server_build["build_backend"] = "incompatible.build"
    server_artifact = _nested_mapping(server_build, "artifact_contract")
    server_artifact["console_command"] = "incompatible-server-console"
    server_build["artifact_contract"] = server_artifact
    builds["server"] = server_build
    crypto_build = _nested_mapping(builds, "crypto")
    crypto_build["distribution"] = "incompatible-crypto-distribution"
    crypto_artifact = _nested_mapping(crypto_build, "artifact_contract")
    crypto_artifact["native_extension_module"] = "incompatible_crypto"
    crypto_build["artifact_contract"] = crypto_artifact
    builds["crypto"] = crypto_build
    baseline["builds"] = builds

    validation = _nested_mapping(baseline, "validation")
    validation_commands = _nested_mapping(validation, "commands")
    quality_command = _nested_mapping(validation_commands, "quality")
    quality_argv = _string_list_value(quality_command, "argv")
    quality_argv[-1] = "incompatible-quality"
    quality_command["argv"] = quality_argv
    quality_command["source"] = "missing-validation-source"
    validation_commands["quality"] = quality_command
    validation["commands"] = validation_commands
    validation["pytest_testpaths"] = ["missing-test-path"]
    validation_evidence = _nested_mapping(validation, "required_command_evidence")
    ci_evidence = _string_list_value(validation_evidence, "scripts/ci.sh")
    ci_evidence.append("missing validation command evidence")
    validation_evidence["scripts/ci.sh"] = ci_evidence
    validation["required_command_evidence"] = validation_evidence
    baseline["validation"] = validation


def _mutate_migration_contract(baseline: dict[str, object]) -> None:
    """Alembic revision chainとheadのcurrent sourceと矛盾する値を作る.

    Args:
        baseline (dict[str, object]): testが変更するpreflight baseline document.

    Returns:
        None: migration categoryを改ざんし、呼び出し側へ値を返さずに完了する.
    """
    migrations = _nested_mapping(baseline, "migrations")
    revision_chain = _string_list_value(migrations, "revision_chain")
    revision_chain[0] = "incompatible-revision-chain-head"
    migrations["revision_chain"] = revision_chain
    migrations["head"] = "incompatible-head"
    baseline["migrations"] = migrations


def _mutate_manifest_paths(baseline: dict[str, object]) -> None:
    """全manifest pathを存在しないbaseline pathへ変更する.

    Args:
        baseline (dict[str, object]): testが変更するpreflight baseline document.

    Returns:
        None: server、crypto、validation、Cargo manifest pathを改ざんして完了する.
    """
    builds = _nested_mapping(baseline, "builds")
    server = _nested_mapping(builds, "server")
    server["manifest"] = "missing-server-manifest.toml"
    builds["server"] = server
    crypto = _nested_mapping(builds, "crypto")
    crypto["manifest"] = "missing-crypto-manifest.toml"
    builds["crypto"] = crypto
    baseline["builds"] = builds

    validation = _nested_mapping(baseline, "validation")
    validation["manifest"] = "missing-validation-manifest.toml"
    baseline["validation"] = validation

    cleanup = _nested_mapping(baseline, "cleanup_inventory")
    exclusions = _nested_mapping(cleanup, "scope_exclusions")
    exclusions["crypto_cargo_manifest"] = "missing-crypto-manifest.toml"
    cleanup["scope_exclusions"] = exclusions
    baseline["cleanup_inventory"] = cleanup


def test_preflight_baseline_uses_recorded_manifest_paths(tmp_path: Path) -> None:
    """Baselineにrecordしたmanifest pathがmissingなら対象categoryを拒否することを検証する.

    Server、crypto、validation、Cargoのmanifest pathを同時に存在しないpathへ変え、checkerが
    hard-coded pathへfallbackせず、各recorded pathをmismatchとして報告することを確認する.

    Args:
        tmp_path (Path): 改ざんしたbaselineを隔離して保存する一時directory.

    Returns:
        None: 全manifest path categoryのmismatchを検証して完了し、呼び出し側へ値を返さない.
    """
    baseline = _load_baseline_document()
    _mutate_manifest_paths(baseline)

    result = _run_checker(_write_mutated_baseline(tmp_path, baseline))

    assert result.returncode != 0
    assert "BASELINE MISMATCH: Build manifest is missing for server" in result.stderr
    assert "BASELINE MISMATCH: Build manifest is missing for crypto" in result.stderr
    assert "BASELINE MISMATCH: Validation manifest is missing" in result.stderr
    assert "BASELINE MISMATCH: Crypto Cargo manifest is missing" in result.stderr


def test_preflight_kiro_inventory_accepts_completed_task_checkbox(tmp_path: Path) -> None:
    """Kiro inventoryがTask 1.1の完了checkbox変更後もtask identityを検証することを確認する.

    Temporary Kiro tree内でTask 1.1を`[x]`へ更新し、current spec、historical evidence、TODO
    inventoryが揃っていればcheckbox stateにかかわらず差分なしになることを確認する.

    Args:
        tmp_path (Path): Kiro inventoryを再現する一時repository root.

    Returns:
        None: 完了checkboxを含むKiro inventoryの検証結果を確認して完了する.
    """
    document = _load_baseline_document()
    cleanup = _nested_mapping(document, "cleanup_inventory")
    todo_status = _nested_mapping(cleanup, "kiro_todo_status")
    task_source = tmp_path / str(todo_status["task_source"])
    task_source.parent.mkdir(parents=True)
    _ = task_source.write_text(
        "- [x] 1.1 移行前の互換contractとcleanup inventoryを固定する\n",
        encoding="utf-8",
    )
    current_spec = tmp_path / ".kiro/specs/monorepo-migration"
    current_spec.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".kiro/specs/completed-spec").mkdir(parents=True)
    todo_path = tmp_path / str(todo_status["todo_path"])
    _ = todo_path.write_text("\n".join(f"TODO {number}" for number in range(6)), encoding="utf-8")

    differences = check_kiro_and_todo_inventory(tmp_path, cleanup)

    assert differences == []


def _mutate_cleanup_inventory(baseline: dict[str, object]) -> None:
    """Cleanup inventoryのcurrent sourceと矛盾する値を作る.

    Args:
        baseline (dict[str, object]): testが変更するpreflight baseline document.

    Returns:
        None: cleanup inventory categoryを改ざんし、呼び出し側へ値を返さずに完了する.
    """
    cleanup = _nested_mapping(baseline, "cleanup_inventory")
    legacy = _nested_mapping(cleanup, "legacy_task_capabilities")
    ci_capabilities = _nested_mapping(legacy, "scripts/ci.sh")
    ci_commands = _string_list_value(ci_capabilities, "commands")
    ci_commands.append("incompatible-legacy-command")
    ci_capabilities["commands"] = ci_commands
    legacy["scripts/ci.sh"] = ci_capabilities
    worktree_capabilities = _nested_mapping(legacy, "scripts/agent-worktree.sh")
    worktree_capabilities["retained"] = False
    worktree_evidence = _string_list_value(worktree_capabilities, "source_evidence")
    worktree_evidence[0] = "missing agent worktree evidence"
    worktree_capabilities["source_evidence"] = worktree_evidence
    legacy["scripts/agent-worktree.sh"] = worktree_capabilities
    cleanup["legacy_task_capabilities"] = legacy
    pre_cutover_paths = _string_list_value(cleanup, "pre_cutover_cleanup_paths")
    pre_cutover_paths.append("missing-pre-cutover-path")
    cleanup["pre_cutover_cleanup_paths"] = pre_cutover_paths
    tracked_templates = _string_list_value(cleanup, "tracked_templates")
    tracked_templates.append("missing-template.example")
    cleanup["tracked_templates"] = tracked_templates
    cleanup["generated_state"] = ["pyproject.toml"]
    normative_paths = _string_list_value(cleanup, "normative_current_paths")
    normative_paths.append("missing-normative-path.md")
    cleanup["normative_current_paths"] = normative_paths
    historical = _nested_mapping(cleanup, "historical_kiro_evidence")
    historical["current_spec"] = ".kiro/specs/missing-current-spec"
    historical["current_spec_is_normative"] = False
    historical["historical_specs_are_non_normative"] = False
    cleanup["historical_kiro_evidence"] = historical
    todo_status = _nested_mapping(cleanup, "kiro_todo_status")
    todo_status["todo_minimum_nonempty_lines"] = 999
    cleanup["kiro_todo_status"] = todo_status
    exclusions = _nested_mapping(cleanup, "scope_exclusions")
    root_workspace_files = _string_list_value(exclusions, "forbidden_root_workspace_files")
    root_workspace_files.append("pyproject.toml")
    exclusions["forbidden_root_workspace_files"] = root_workspace_files
    forbidden_process_names = _string_list_value(exclusions, "forbidden_process_names")
    forbidden_process_names.append("app")
    exclusions["forbidden_process_names"] = forbidden_process_names
    root_dependencies = _string_list_value(exclusions, "root_python_dependencies")
    root_dependencies.append("incompatible-dependency")
    exclusions["root_python_dependencies"] = root_dependencies
    crypto_library = _nested_mapping(exclusions, "crypto_library")
    crypto_library["name"] = "incompatible_crypto_library"
    exclusions["crypto_library"] = crypto_library
    cleanup["scope_exclusions"] = exclusions
    baseline["cleanup_inventory"] = cleanup


def _assert_expected_mismatch_markers(stderr: str) -> None:
    """各baseline categoryが変更を報告したことを検証する.

    Args:
        stderr (str): 改ざんしたbaselineに対するcheckerの標準error出力.

    Returns:
        None: 必須のmismatch markerをすべて検証し、呼び出し側へ値を返さずに完了する.
    """
    markers = [
        "Python namespace contract changed",
        "App invocation changed",
        "App ASGI target changed",
        "Worker entrypoint changed",
        "Worker task names changed",
        "Console command changed",
        "CLI import namespace changed",
        "CLI command groups changed",
        "CLI confirmation contract evidence is missing",
        "CLI exit contract evidence is missing",
        "Alembic revision chain changed",
        "Alembic head changed",
        "Build command changed for server",
        "Server distribution name changed",
        "Server build backend changed",
        "Server artifact console command changed",
        "Crypto distribution name changed",
        "Crypto artifact native extension module changed",
        "Validation command changed for quality",
        "Validation command source changed for quality",
        "Pytest target paths changed",
        "Validation command evidence is missing",
        "Legacy task capability is missing",
        "Legacy agent worktree helper is no longer retained",
        "Tracked template is missing",
        "Generated or machine-specific state is tracked",
        "Normative current path is missing",
        "Pre-cutover cleanup inventory path is missing",
        "Current Kiro spec path is missing",
        "Current Kiro spec is not classified as normative",
        "Historical Kiro specs are not classified as non-normative",
        "Kiro TODO has fewer",
        "Scope-excluded root workspace file exists",
        "Scope-excluded process is configured",
        "Frozen root Python dependencies changed",
        "Crypto library name changed",
    ]
    for marker in markers:
        assert f"BASELINE MISMATCH: {marker}" in stderr


def test_preflight_baseline_rejects_mutated_enforced_contracts(tmp_path: Path) -> None:
    """各enforced baseline categoryの期待値変更をmismatchとして拒否する契約を検証する.

    Runtime、CLI、build、validation、cleanup inventoryの期待値を同時に変え、各categoryの
    mismatch evidenceがstderrへ残ることを確認する.

    Args:
        tmp_path (Path): 改ざんしたbaselineを隔離して保存する一時directory.

    Returns:
        None: 全enforced categoryの拒否結果を検証して完了し、呼び出し側へ値を返さない.
    """
    baseline = _load_baseline_document()
    _mutate_runtime_and_cli_contract(baseline)
    _mutate_migration_contract(baseline)
    _mutate_build_and_validation_contract(baseline)
    _mutate_cleanup_inventory(baseline)

    result = _run_checker(_write_mutated_baseline(tmp_path, baseline))

    assert result.returncode != 0
    _assert_expected_mismatch_markers(result.stderr)


def test_preflight_baseline_rejects_unreachable_alembic_current() -> None:
    """opt-in Alembic current checkが到達不能databaseを成功として扱わないことを検証する.

    DATABASE_URLを接続を待ち受けないloopback portへ固定してcheckerを実行し、通常baselineが
    一致していてもAlembic currentの実行不能をnon-zero exitとmismatch表示で返すことを確認する.

    Returns:
        None: opt-in Alembic current checkの失敗結果を検証して完了し、呼び出し側へ値を返さない.
    """
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql+asyncpg://user:pass@127.0.0.1:1/athena"

    result = _run_checker(BASELINE_PATH, alembic_current=True, environment=environment)

    assert result.returncode != 0
    assert "BASELINE MISMATCH" in result.stderr
    assert "Alembic current check could not run" in result.stderr
