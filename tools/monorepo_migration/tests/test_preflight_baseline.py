"""monorepo移行前baselineの再検証契約を検証する."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
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

REPOSITORY_ROOT = Path(__file__).parents[3]
BASELINE_PATH = REPOSITORY_ROOT / ".kiro/specs/monorepo-migration/preflight-baseline.json"
VERIFIER_PATH = REPOSITORY_ROOT / "tools/monorepo_migration/verify_preflight_baseline.py"
GIT_SHA1_HEX_LENGTH = 40


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
        environment (dict[str, str] | None): child processへ渡す環境変数. Noneなら現在の環境を
            使用し、いずれの場合も親Git repositoryのlocal contextは除去する.
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
        env=_git_environment_without_parent_repository(environment),
        text=True,
        timeout=30,
    )


def _recorded_pre_cutover_source_revision() -> str:
    """Baselineを採取したpre-cutover Git revisionを返す.

    Returns:
        str: 40文字のlowercase SHA-1 object IDとして記録されたsource revision.

    Raises:
        TypeError: verification fieldまたはsource revisionが期待するJSON型でない場合.
        ValueError: source revisionが完全なlowercase SHA-1 object IDでない場合.
    """
    verification = _nested_mapping(_load_baseline_document(), "verification")
    revision = verification["pre_cutover_source_revision"]
    if not isinstance(revision, str):
        raise TypeError("verification.pre_cutover_source_revision must be a string")
    if len(revision) != GIT_SHA1_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise ValueError(
            "verification.pre_cutover_source_revision must be a full lowercase SHA-1 object ID"
        )
    return revision


def _make_immutable_pre_cutover_repository(tmp_path: Path) -> Path:
    """Task 1.1の記録済みtreeをGit index付きtemporary repositoryへ展開する.

    現在のHEADやworktreeが後続taskで変化しても、Task 1.1が固定したpre-cutover inventoryを
    記録済みcommitのsourceとindexに対して検証できるfixtureを作る.

    Args:
        tmp_path (Path): archiveを展開してtemporary Git repositoryにするdirectory.

    Returns:
        Path: immutable Task 1.1 snapshotをindexへ登録済みのrepository root.

    Raises:
        AssertionError: Git archiveの取得、展開後repositoryの初期化、またはindex登録に失敗した場合.
    """
    source_revision = _recorded_pre_cutover_source_revision()
    git_environment = _git_environment_without_parent_repository()
    archive_process = subprocess.run(
        ["git", "archive", "--format=tar", source_revision],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        env=git_environment,
    )

    assert archive_process.returncode == 0, archive_process.stderr.decode(encoding="utf-8")
    with tarfile.open(fileobj=io.BytesIO(archive_process.stdout), mode="r:") as archive:
        archive.extractall(tmp_path, filter="data")

    initialize_process = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )
    index_process = subprocess.run(
        ["git", "add", "--all"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )

    assert initialize_process.returncode == 0, initialize_process.stderr
    assert index_process.returncode == 0, index_process.stderr
    # `git check-ignore`がdirectory-only patternを検証するには実pathが必要である.
    # これらはTask 1.1のhistorical generated-state inventoryに含まれる.
    (tmp_path / ".state").mkdir()
    (tmp_path / "certs").mkdir()
    return tmp_path


def _extract_recorded_pre_cutover_paths(destination: Path, relative_paths: list[str]) -> None:
    """Task 1.1の記録済みrevisionから指定pathだけを展開する.

    Args:
        destination (Path): historical sourceを展開する空directory.
        relative_paths (list[str]): repository rootからの展開対象path.

    Returns:
        None: 記録済みrevisionの指定pathを展開し、呼び出し側へ値を返さない.

    Raises:
        AssertionError: Git archiveを取得できない場合.
    """
    destination.mkdir(parents=True, exist_ok=True)
    archive_process = subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            _recorded_pre_cutover_source_revision(),
            "--",
            *relative_paths,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        env=_git_environment_without_parent_repository(),
    )

    assert archive_process.returncode == 0, archive_process.stderr.decode(encoding="utf-8")
    with tarfile.open(fileobj=io.BytesIO(archive_process.stdout), mode="r:") as archive:
        archive.extractall(destination, filter="data")


def _make_post_cutover_repository(tmp_path: Path) -> Path:
    """予定済みのserver/crypto relocationだけを再現するtemporary repositoryを作る.

    旧root source、Alembic、legacy scriptを作らず、current root task gatewayとowner workspaceを
    配置してTask 1.1のpost-cutover compatibility modeを確認するfixtureである.

    Args:
        tmp_path (Path): fixture repositoryを作成する一時directory.

    Returns:
        Path: `apps/athena_server`と`packages/athena_crypto`を含むrepository root.
    """
    repository_root = tmp_path / "repository"
    server_root = repository_root / "apps/athena_server"
    crypto_root = repository_root / "packages/athena_crypto"
    ignored_paths = shutil.ignore_patterns("__pycache__", ".pytest_cache", "target")
    _ = shutil.copytree(
        REPOSITORY_ROOT / "apps/athena_server/src",
        server_root / "src",
        ignore=ignored_paths,
    )
    _ = (server_root / "tests").mkdir()
    _ = shutil.copytree(
        REPOSITORY_ROOT / "apps/athena_server/alembic",
        server_root / "alembic",
        ignore=ignored_paths,
    )
    _ = shutil.copytree(
        REPOSITORY_ROOT / "packages/athena_crypto",
        crypto_root,
        ignore=ignored_paths,
    )
    _ = shutil.copy2(
        REPOSITORY_ROOT / "apps/athena_server/pyproject.toml",
        server_root / "pyproject.toml",
    )
    _ = shutil.copy2(
        REPOSITORY_ROOT / "apps/athena_server/alembic.ini",
        server_root / "alembic.ini",
    )
    _ = shutil.copy2(REPOSITORY_ROOT / "pyproject.toml", repository_root / "pyproject.toml")
    _ = shutil.copy2(REPOSITORY_ROOT / "justfile", repository_root / "justfile")
    _ = shutil.copy2(REPOSITORY_ROOT / "flake.nix", repository_root / "flake.nix")
    monorepo_tooling_root = repository_root / "tools/monorepo_migration"
    monorepo_tooling_root.mkdir(parents=True)
    for helper_name in ("repository_validation.sh", "test_database_tasks.sh"):
        _ = shutil.copy2(
            REPOSITORY_ROOT / "tools/monorepo_migration" / helper_name,
            monorepo_tooling_root / helper_name,
        )
    _ = shutil.copytree(
        REPOSITORY_ROOT / "tools/gitlint",
        repository_root / "tools/gitlint",
        ignore=ignored_paths,
    )
    _ = shutil.copy2(REPOSITORY_ROOT / ".gitignore", repository_root / ".gitignore")
    _ = shutil.copy2(
        REPOSITORY_ROOT / "process-compose.yml",
        repository_root / "process-compose.yml",
    )
    _ = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        env=_git_environment_without_parent_repository(),
        text=True,
    )
    return repository_root


def _make_crypto_cutover_repository(tmp_path: Path) -> Path:
    """Cryptoだけを移設しserverはlegacy rootに残すtemporary repositoryを作る.

    Args:
        tmp_path (Path): fixture repositoryを作成する一時directory.

    Returns:
        Path: legacy server pathと`packages/athena_crypto`を含むrepository root.
    """
    crypto_root = tmp_path / "packages/athena_crypto"
    ignored_paths = shutil.ignore_patterns("__pycache__", ".pytest_cache", "target")
    _extract_recorded_pre_cutover_paths(
        tmp_path,
        ["src", "alembic", "alembic.ini", "pyproject.toml"],
    )
    _ = shutil.copytree(
        REPOSITORY_ROOT / "packages/athena_crypto",
        crypto_root,
        ignore=ignored_paths,
    )
    return tmp_path


def _git_environment_without_parent_repository(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """任意のrepositoryをcwdで選べるよう親Git local contextを除いた環境を返す.

    Args:
        environment (Mapping[str, str] | None): 隔離前のprocess環境. Noneなら現在の環境を使う.

    Returns:
        dict[str, str]: caller指定値を維持し、Gitが列挙したrepository-local variablesだけを
            除いたprocess環境.

    Raises:
        AssertionError: Gitがlocal environment variable名を列挙できない場合.
    """
    discovery_environment = {
        variable_name: value
        for variable_name, value in os.environ.items()
        if not variable_name.startswith("GIT_")
    }
    local_variables_process = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        env=discovery_environment,
        text=True,
    )
    assert local_variables_process.returncode == 0, local_variables_process.stderr

    isolated_environment = dict(os.environ if environment is None else environment)
    for variable_name in local_variables_process.stdout.splitlines():
        _ = isolated_environment.pop(variable_name, None)
    return isolated_environment


def test_pre_cutover_fixture_uses_recorded_revision_after_head_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current HEADが進んでも記録済みpre-cutover revisionを展開することを検証する.

    2つのcommitを持つtemporary repositoryでTask 1.1相当のrevisionをbaselineへ記録し、HEADを
    後続commitへ進めた後もhistorical fixtureが最初のsource内容を復元することを確認する.

    Args:
        tmp_path (Path): source repository、baseline、展開先を隔離する一時directory.
        monkeypatch (pytest.MonkeyPatch): fixtureが参照するrepositoryとbaseline pathを差し替える
            pytest helper.

    Returns:
        None: 記録済みrevisionのsource内容を検証して完了し、呼び出し側へ値を返さない.
    """
    source_repository = tmp_path / "source"
    source_repository.mkdir()
    tracked_path = source_repository / "layout.txt"
    _ = tracked_path.write_text("pre-cutover\n", encoding="utf-8")
    git_environment = _git_environment_without_parent_repository()
    initialize_process = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=source_repository,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )
    add_process = subprocess.run(
        ["git", "add", "layout.txt"],
        cwd=source_repository,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )
    first_commit_process = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Athena Tests",
            "-c",
            "user.email=tests@athena.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "--quiet",
            "-m",
            "pre-cutover",
        ],
        cwd=source_repository,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )
    revision_process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_repository,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )

    assert initialize_process.returncode == 0, initialize_process.stderr
    assert add_process.returncode == 0, add_process.stderr
    assert first_commit_process.returncode == 0, first_commit_process.stderr
    assert revision_process.returncode == 0, revision_process.stderr
    pre_cutover_revision = revision_process.stdout.strip()

    _ = tracked_path.write_text("current\n", encoding="utf-8")
    second_add_process = subprocess.run(
        ["git", "add", "layout.txt"],
        cwd=source_repository,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )
    second_commit_process = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Athena Tests",
            "-c",
            "user.email=tests@athena.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "--quiet",
            "-m",
            "current",
        ],
        cwd=source_repository,
        check=False,
        capture_output=True,
        env=git_environment,
        text=True,
    )
    assert second_add_process.returncode == 0, second_add_process.stderr
    assert second_commit_process.returncode == 0, second_commit_process.stderr

    baseline_path = tmp_path / "preflight-baseline.json"
    _ = baseline_path.write_text(
        json.dumps(
            {
                "verification": {
                    "pre_cutover_source_revision": pre_cutover_revision,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "REPOSITORY_ROOT", source_repository)
    monkeypatch.setitem(globals(), "BASELINE_PATH", baseline_path)
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir()

    repository_root = _make_immutable_pre_cutover_repository(snapshot_root)

    assert (repository_root / "layout.txt").read_text(encoding="utf-8") == "pre-cutover\n"


def test_pre_cutover_mode_accepts_recorded_revision_inventory(tmp_path: Path) -> None:
    """Pre-cutover modeが記録済みrevision上のhistorical inventoryを受理することを検証する.

    Task 1.2のcrypto relocationによる中間treeをcurrent repositoryで検証する代わりに、Task 1.1が
    baselineへ記録したpre-cutover sourceとGit indexを展開し、historical cleanup contractの
    coverageをHEADから独立して維持する.

    Args:
        tmp_path (Path): immutable pre-cutover fixtureを隔離する一時directory.

    Returns:
        None: pre-cutover checkerが差分なしで完了することを検証して完了する.
    """
    repository_root = _make_immutable_pre_cutover_repository(tmp_path)

    result = _run_checker(
        BASELINE_PATH,
        mode="pre-cutover",
        repository_root=repository_root,
    )

    assert result.returncode == 0, result.stderr


def test_crypto_cutover_mode_accepts_relocated_crypto_with_legacy_server_layout(
    tmp_path: Path,
) -> None:
    """Crypto-cutover modeがcryptoだけを移設した中間layoutを受理することを検証する.

    server productの`src`、Alembic、root manifestはlegacy pathに残し、crypto artifactだけを
    `packages/athena_crypto`へ配置したtreeを検証する.

    Args:
        tmp_path (Path): crypto-only relocation fixtureを隔離する一時directory.

    Returns:
        None: crypto-only semantic preflightが差分なしで完了することを検証する.
    """
    repository_root = _make_crypto_cutover_repository(tmp_path)

    result = _run_checker(
        BASELINE_PATH,
        mode="crypto-cutover",
        repository_root=repository_root,
    )

    assert result.returncode == 0, result.stderr
    assert (repository_root / "src/osu_server/__main__.py").is_file()
    assert (repository_root / "packages/athena_crypto/Cargo.toml").is_file()
    assert not (repository_root / "apps/athena_server").exists()


def test_crypto_cutover_mode_rejects_missing_relocated_crypto(tmp_path: Path) -> None:
    """Crypto-cutover modeがcrypto relocation targetの欠落を拒否することを検証する.

    legacy server rootだけが残り`packages/athena_crypto`がないtreeを検証し、semantic viewを作る前に
    relocation targetの欠落をoperatorが識別できるmismatchとして報告することを確認する.

    Args:
        tmp_path (Path): crypto-only relocation fixtureを隔離する一時directory.

    Returns:
        None: relocation targetの欠落がnon-zero exitになることを検証して完了する.
    """
    repository_root = _make_crypto_cutover_repository(tmp_path)
    _ = (repository_root / "packages/athena_crypto").rename(repository_root / "unavailable-crypto")

    result = _run_checker(
        BASELINE_PATH,
        mode="crypto-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert (
        "BASELINE MISMATCH: Crypto-cutover relocation target is missing: packages/athena_crypto"
        in result.stderr
    )


def test_crypto_cutover_mode_rejects_retained_legacy_crypto_path(tmp_path: Path) -> None:
    """Crypto-cutover modeが移設後も残ったlegacy crypto pathを拒否することを検証する.

    crypto packageを新旧両方のpathに置いたtreeを検証し、二重のartifact authorityを許容せず
    `athena-crypto`のretired stateをmismatchとして報告することを確認する.

    Args:
        tmp_path (Path): crypto-only relocation fixtureを隔離する一時directory.

    Returns:
        None: legacy crypto pathがnon-zero exitになることを検証して完了する.
    """
    repository_root = _make_crypto_cutover_repository(tmp_path)
    _ = shutil.copytree(
        repository_root / "packages/athena_crypto",
        repository_root / "athena-crypto",
    )

    result = _run_checker(
        BASELINE_PATH,
        mode="crypto-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert (
        "BASELINE MISMATCH: Crypto-cutover retired path is still present: athena-crypto"
        in result.stderr
    )


def test_crypto_cutover_mode_rejects_premature_server_workspace(tmp_path: Path) -> None:
    """Crypto-cutover modeがserver workspaceの早期移設を拒否することを検証する.

    server sourceがlegacy rootにも`apps/athena_server`にも存在するtreeを検証し、server移設は
    crypto-only cutoverの範囲外としてmismatchになることを確認する.

    Args:
        tmp_path (Path): crypto-only relocation fixtureを隔離する一時directory.

    Returns:
        None: premature server workspaceがnon-zero exitになることを検証して完了する.
    """
    repository_root = _make_crypto_cutover_repository(tmp_path)
    (repository_root / "apps/athena_server").mkdir(parents=True)

    result = _run_checker(
        BASELINE_PATH,
        mode="crypto-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert (
        "BASELINE MISMATCH: Crypto-cutover forbidden path is present: apps/athena_server"
        in result.stderr
    )


def test_preflight_baseline_matches_current_repository_contract(tmp_path: Path) -> None:
    """Server cutover後のruntimeとcurrent root validation policyを検証する.

    現在のserver source/manifestとroot validation manifestを使い、後続Task 2.2で移すAlembicだけを
    owner pathへ投影したfixtureにpost-cutover checkerを実行する. これによりruntime semantic viewと
    repository-wide validation policyを別rootから検証できることを確認する.

    Args:
        tmp_path (Path): post-cutover semantic fixtureを隔離する一時directory.

    Returns:
        None: checkerの成功終了を検証して完了し、呼び出し側へ値を返さない.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert result.returncode == 0, result.stderr
    assert "Alembic current was not checked." in result.stdout


def test_post_cutover_mode_requires_root_task_interface(tmp_path: Path) -> None:
    """Post-cutover validationがcanonical root task interfaceの欠落を拒否する契約を検証する.

    Owner workspaceとpytest policyだけを持つfixtureからroot Just interfaceを除き、current
    validation contractがlegacy helperへfallbackせずmigration incompleteとして報告することを
    確認する.

    Args:
        tmp_path (Path): Root task interfaceを欠くpost-cutover fixtureを置くtemporary directory.

    Returns:
        None: Missing public task sourceがnon-zeroとdiagnosticを返すことを検証して完了する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    task_interface_path = repository_root / "justfile"
    if task_interface_path.exists():
        task_interface_path.unlink()

    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert "Root task interface source is missing: justfile" in result.stderr


def test_post_cutover_mode_rejects_legacy_task_consumer(tmp_path: Path) -> None:
    """Post-cutover validationがroot recipeを迂回するcurrent consumerを拒否する契約を検証する.

    Flake hookをlegacy docstring helperへ戻したfixtureを検査し、public Just interfaceとの乖離を
    current validation contractが明示的に報告することを確認する.

    Args:
        tmp_path (Path): Legacy Flake consumerを持つpost-cutover fixture用temporary directory.

    Returns:
        None: Current consumerのdeprecated helper参照がnon-zeroになることを検証して完了する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    flake_path = repository_root / "flake.nix"
    flake_source = flake_path.read_text(encoding="utf-8").replace(
        'entry = "just docstrings";',
        'entry = "./scripts/ci.sh docstrings";',
    )
    _ = flake_path.write_text(flake_source, encoding="utf-8")

    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert "Root task consumer still uses legacy helper: flake.nix scripts/ci.sh" in result.stderr


def test_post_cutover_mode_rejects_incomplete_or_legacy_root_task_interface(
    tmp_path: Path,
) -> None:
    """Post-cutover validationがmissing recipeとlegacy helper dependencyを同時に拒否する.

    Public `fix` recipeをprivate名へ変更し、Just sourceへdeprecated database helper参照を加えた
    fixtureで、discoverabilityとconsumer-free ownershipの両方を検査する.

    Args:
        tmp_path (Path): Mutated root task interfaceを持つfixture用temporary directory.

    Returns:
        None: Missing recipeとlegacy dependencyのdiagnosticを検証して完了する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    justfile_path = repository_root / "justfile"
    justfile_source = justfile_path.read_text(encoding="utf-8")
    assert "fix:\n" in justfile_source
    mutated_source = justfile_source.replace("fix:\n", "_fix:\n", 1)
    mutated_source += "\n# forbidden current consumer: scripts/dev-tasks.sh\n"
    _ = justfile_path.write_text(mutated_source, encoding="utf-8")

    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert "Root task interface is missing public recipes: ['fix']" in result.stderr
    assert (
        "Root task interface still consumes legacy helper: scripts/dev-tasks.sh" in result.stderr
    )


def test_post_cutover_mode_accepts_relocated_contract_without_pre_cutover_inventory(
    tmp_path: Path,
) -> None:
    """Post-cutover modeが予定済みrelocation後も意味的contractを比較することを検証する.

    旧root source、Alembic、manifest、legacy scriptを持たずcurrent root task gatewayを持つfixtureに
    対してpost-cutover modeが成功することを確認する. Gitlint rule/testはrepository tool ownerへ
    移設し、
    generated cacheだけを含むroot `tests`はsource authorityの重複と扱わない. 同じtreeを
    pre-cutover modeで検証した場合はinventory mismatchになる.

    Args:
        tmp_path (Path): relocation済みfixtureを隔離する一時directory.

    Returns:
        None: physical pathのpreflight inventory、owner-scoped test inventory、semantic
            compatibility modeの分離を検証する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    assert (repository_root / "justfile").is_file()
    stale_cache_path = repository_root / "tests/unit/__pycache__/test_stale.cpython-314.pyc"
    stale_cache_path.parent.mkdir(parents=True)
    stale_cache_path.touch()

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

    mutated_baseline = _load_baseline_document()
    compatibility = _nested_mapping(mutated_baseline, "post_cutover_compatibility")
    validation = _nested_mapping(compatibility, "validation")
    validation["pytest_testpaths"] = ["apps/athena_server/tests"]
    compatibility["validation"] = validation
    mutated_baseline["post_cutover_compatibility"] = compatibility

    mutated_post_cutover_result = _run_checker(
        _write_mutated_baseline(tmp_path, mutated_baseline),
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert mutated_post_cutover_result.returncode != 0
    assert "Pytest target paths changed" in mutated_post_cutover_result.stderr


def test_post_cutover_mode_rejects_root_test_without_an_owner(
    tmp_path: Path,
) -> None:
    """Post-cutover modeがownerのないroot testを拒否することを検証する.

    Server/Gitlint test移設後にroot testが残るとowner boundaryの抜け穴になるため、任意のtest
    fileを追加したfixtureがnon-zeroで停止することを確認する.

    Args:
        tmp_path (Path): relocation済みfixtureを隔離する一時directory.

    Returns:
        None: 非許可root testを含むpost-cutover fixtureの拒否を検証して完了する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    unexpected_root_test = repository_root / "tests/test_repository_tooling.py"
    unexpected_root_test.parent.mkdir(parents=True)
    _ = unexpected_root_test.write_text("", encoding="utf-8")

    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert "BASELINE MISMATCH: Post-cutover retired path is still present: tests" in result.stderr


def test_post_cutover_mode_rejects_retained_legacy_server_source(tmp_path: Path) -> None:
    """Post-cutover modeが移設後も残るlegacy server sourceを拒否することを検証する.

    `apps/athena_server`へ移設済みのfixtureへ旧root `src`を追加し、server workspaceの二重
    authorityをpost-cutover semantic contractが許容しないことを確認する.

    Args:
        tmp_path (Path): relocation済みfixtureを隔離する一時directory.

    Returns:
        None: legacy server sourceの併存がnon-zero exitになることを検証して完了する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    _ = shutil.copytree(
        repository_root / "apps/athena_server/src",
        repository_root / "src",
    )

    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert "BASELINE MISMATCH: Post-cutover retired path is still present: src" in result.stderr


def test_post_cutover_mode_rejects_retained_legacy_crypto_package(tmp_path: Path) -> None:
    """Post-cutover modeが移設後も残るlegacy crypto packageを拒否することを検証する.

    `packages/athena_crypto`へ移設済みのfixtureへ旧`athena-crypto`を追加し、native artifactの
    二重authorityをpost-cutover semantic contractが許容しないことを確認する.

    Args:
        tmp_path (Path): relocation済みfixtureを隔離する一時directory.

    Returns:
        None: legacy crypto packageの併存がnon-zero exitになることを検証して完了する.
    """
    repository_root = _make_post_cutover_repository(tmp_path)
    ignored_paths = shutil.ignore_patterns("__pycache__", ".pytest_cache", "target")
    _ = shutil.copytree(
        REPOSITORY_ROOT / "packages/athena_crypto",
        repository_root / "athena-crypto",
        ignore=ignored_paths,
    )

    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        repository_root=repository_root,
    )

    assert result.returncode != 0
    expected = "BASELINE MISMATCH: Post-cutover retired path is still present: athena-crypto"
    assert expected in result.stderr


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


def test_post_cutover_alembic_current_on_crypto_cutover_tree_reports_mismatches(
    tmp_path: Path,
) -> None:
    """Crypto-cutover treeのpost-cutover Alembic current mismatchを検証する.

    Serverがrootに残る中間layoutから`--mode post-cutover --alembic-current`を実行し、server
    relocation不足とserver workspace不足をouter CLI errorではなく同じbaseline mismatch reportへ
    収集することを確認する.

    Returns:
        None: physical layoutとAlembic command rootの差分がstderrへ報告されることを検証して
            完了する.
    """
    repository_root = _make_crypto_cutover_repository(tmp_path)
    result = _run_checker(
        BASELINE_PATH,
        mode="post-cutover",
        alembic_current=True,
        repository_root=repository_root,
    )

    assert result.returncode != 0
    assert "BASELINE MISMATCH: Post-cutover relocation target is missing" in result.stderr
    assert "BASELINE MISMATCH: Alembic current command root is missing" in result.stderr
    assert "Baseline verification could not complete" not in result.stderr


def test_alembic_current_runner_oserror_is_reported_as_mismatch() -> None:
    """Alembic runnerのOS errorをbaseline mismatchへ変換することを検証する.

    実行可能なcrypto-cutover rootへOS errorを送出するrunnerを注入し、runner failureがchecker全体の
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
        mode=VerificationMode.CRYPTO_CUTOVER,
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
        mode=VerificationMode.CRYPTO_CUTOVER,
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

    result = _run_checker(
        _write_mutated_baseline(tmp_path, document),
        mode="crypto-cutover",
        repository_root=_make_crypto_cutover_repository(tmp_path / "repository"),
    )

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
        mode=VerificationMode.CRYPTO_CUTOVER,
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
        mode=VerificationMode.CRYPTO_CUTOVER,
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
    repository_root = _make_immutable_pre_cutover_repository(tmp_path)

    result = _run_checker(
        _write_mutated_baseline(tmp_path, baseline),
        mode="pre-cutover",
        repository_root=repository_root,
    )

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
    repository_root = _make_immutable_pre_cutover_repository(tmp_path)

    result = _run_checker(
        _write_mutated_baseline(tmp_path, baseline),
        mode="pre-cutover",
        repository_root=repository_root,
    )

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

    result = _run_checker(
        BASELINE_PATH,
        alembic_current=True,
        environment=environment,
        mode="crypto-cutover",
    )

    assert result.returncode != 0
    assert "BASELINE MISMATCH" in result.stderr
    assert "Alembic current check could not run" in result.stderr
