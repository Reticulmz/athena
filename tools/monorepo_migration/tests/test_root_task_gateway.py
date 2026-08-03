"""Root Task Gatewayの明示的setupとdevelopment preflight contractを検証するmodule."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
JUSTFILE_PATH = REPOSITORY_ROOT / "justfile"
SETUP_SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "setup-worktree.sh"


def _write_executable(path: Path, source: str) -> None:
    """指定pathへtest用commandを作成する.

    Args:
        path (Path): 作成するexecutable fileのpath.
        source (str): executableへ書き込むshell source.

    Returns:
        None: sourceを書き込み実行可能にして完了し、呼び出し側へ値を返さない.
    """
    _ = path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    _ = path.chmod(0o755)


def _copy_root_task_gateway(repository_root: Path) -> None:
    """Root Task Gatewayを隔離repositoryへ複製する.

    Args:
        repository_root (Path): gateway fixtureを配置するrepository root.

    Returns:
        None: public justfileとsetup helperを複製して完了する.
    """
    scripts_directory = repository_root / "scripts"
    scripts_directory.mkdir(parents=True)
    _ = shutil.copy2(JUSTFILE_PATH, repository_root / "justfile")
    _ = shutil.copy2(SETUP_SCRIPT_PATH, scripts_directory / "setup-worktree.sh")


def _initialize_git_repository(repository_root: Path) -> None:
    """Setupのworktree判定に使う隔離Git repositoryを初期化する.

    Args:
        repository_root (Path): `.git` directoryを作成するfixture root.

    Returns:
        None: 空のGit repositoryを初期化して完了する.
    """
    _ = subprocess.run(
        ["git", "init", "--quiet", str(repository_root)],
        check=True,
        capture_output=True,
        text=True,
    )


def _fake_setup_environment(repository_root: Path) -> tuple[dict[str, str], Path]:
    """Host trust storeへ触れないsetup用fake tool environmentを作る.

    Args:
        repository_root (Path): fake commandと記録fileを配置するfixture root.

    Returns:
        tuple[dict[str, str], Path]: subprocess environmentとcommand記録fileの組.
    """
    binary_directory = repository_root / "fake-bin"
    binary_directory.mkdir()
    command_log_path = repository_root / "commands.log"
    pre_commit_config_path = repository_root / "generated-pre-commit.yaml"
    _ = pre_commit_config_path.write_text("repos: []\n", encoding="utf-8")

    _write_executable(
        binary_directory / "nix",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'nix:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        [[ "${1:-}" == "build" ]]
        printf '%s\n' "$ATHENA_TEST_PRE_COMMIT_CONFIG"
        """,
    )
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'uv:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        [[ "${1:-}" == "sync" ]]
        mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
        printf '#!/usr/bin/env bash\n' > "$UV_PROJECT_ENVIRONMENT/bin/python"
        chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
        """,
    )
    _write_executable(
        binary_directory / "prek",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'prek:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        git_directory=''
        hook_type='pre-commit'
        while (($#)); do
          case "$1" in
            --config|--git-dir|--hook-type)
              option="$1"
              shift
              [[ "$option" != '--git-dir' ]] || git_directory="$1"
              [[ "$option" != '--hook-type' ]] || hook_type="$1"
              ;;
          esac
          shift
        done
        [[ -n "$git_directory" ]]
        mkdir -p "$git_directory/hooks"
        printf '#!/usr/bin/env bash\n' > "$git_directory/hooks/$hook_type"
        chmod +x "$git_directory/hooks/$hook_type"
        """,
    )
    _write_executable(
        binary_directory / "mkcert",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'mkcert:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        if [[ "${1:-}" == '-install' ]]; then
          exit 0
        fi
        certificate_file=''
        certificate_key_file=''
        while (($#)); do
          case "$1" in
            -cert-file)
              shift
              certificate_file="$1"
              ;;
            -key-file)
              shift
              certificate_key_file="$1"
              ;;
          esac
          shift
        done
        [[ -n "$certificate_file" && -n "$certificate_key_file" ]]
        printf 'fixture certificate\n' > "$certificate_file"
        printf 'fixture private key\n' > "$certificate_key_file"
        """,
    )

    environment = os.environ.copy()
    environment.update(
        {
            "ATHENA_TEST_COMMAND_LOG": str(command_log_path),
            "ATHENA_TEST_PRE_COMMIT_CONFIG": str(pre_commit_config_path),
            "ATHENA_WORKTREE_ROOT": str(repository_root),
            "PATH": f"{binary_directory}:{environment['PATH']}",
        }
    )
    return environment, command_log_path


def _run_just(
    repository_root: Path,
    environment: dict[str, str],
    recipe: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Fixture repositoryのpublic Just recipeを実行する.

    Args:
        repository_root (Path): justfileを所有するfixture repository root.
        environment (dict[str, str]): fake toolを含むsubprocess environment.
        recipe (str): 実行するpublic recipe名.
        *arguments (str): Recipeへ渡す追加argument.

    Returns:
        subprocess.CompletedProcess[str]: captured outputとexit statusを含む実行結果.
    """
    return subprocess.run(
        ["just", "--justfile", str(repository_root / "justfile"), recipe, *arguments],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )


def _create_complete_core_state(repository_root: Path) -> None:
    """Core development preflightを満たすworktree-local stateを作る.

    Args:
        repository_root (Path): `.venv`と`.state`を所有するfixture repository root.

    Returns:
        None: Core profileに必要なPython、state directory、hook、certificateを作成する.
    """
    for directory in (
        repository_root / ".state" / "postgres",
        repository_root / ".state" / "valkey",
        repository_root / ".state" / "nginx",
        repository_root / ".state" / "certs",
        repository_root / ".state" / "cloudflared",
    ):
        _ = directory.mkdir(parents=True)
    for executable_path in (
        repository_root / ".venv" / "bin" / "python",
        repository_root / ".state" / "hooks" / "pre-commit",
        repository_root / ".state" / "hooks" / "commit-msg",
    ):
        executable_path.parent.mkdir(parents=True, exist_ok=True)
        _write_executable(executable_path, "#!/usr/bin/env bash\nexit 0\n")
    for certificate_path in (
        repository_root / ".state" / "certs" / "_wildcard.athena.localhost.pem",
        repository_root / ".state" / "certs" / "_wildcard.athena.localhost-key.pem",
    ):
        _ = certificate_path.write_text("fixture\n", encoding="utf-8")


def test_setup_reexecution_converges_and_reconfirms_local_trust(tmp_path: Path) -> None:
    """Setup再実行がstateを維持しlocal CA trustを再確認するcontractを検証する.

    Host trust storeを変更しないfake mkcertで同じworktreeを2回setupし、locked sync、worktree-local
    state、hook、certificateが利用可能なまま保たれ、idempotentな`mkcert -install`が各回に実行
    されることを確認する.

    Args:
        tmp_path (Path): 隔離Git repositoryとfake toolを配置するpytest temporary directory.

    Returns:
        None: 2回の明示的setupが同じ利用可能状態へ収束することを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)

    first_result = _run_just(repository_root, environment, "setup")
    second_result = _run_just(repository_root, environment, "setup")

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    state_root = repository_root / ".state"
    assert (repository_root / ".venv" / "bin" / "python").is_file()
    for state_directory_name in ("postgres", "valkey", "nginx", "certs", "cloudflared"):
        assert (state_root / state_directory_name).is_dir()
    assert (state_root / "hooks" / "pre-commit").is_file()
    assert (state_root / "hooks" / "commit-msg").is_file()
    assert (state_root / "certs" / "_wildcard.athena.localhost.pem").is_file()
    assert (state_root / "certs" / "_wildcard.athena.localhost-key.pem").is_file()
    assert (repository_root / ".pre-commit-config.yaml").resolve() == (
        repository_root / "generated-pre-commit.yaml"
    )
    hooks_path_result = subprocess.run(
        ["git", "config", "--worktree", "--get", "core.hooksPath"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert hooks_path_result.returncode == 0, hooks_path_result.stderr
    assert hooks_path_result.stdout.strip() == str(state_root / "hooks")

    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert command_log.count(f"uv:sync --project {repository_root} --locked --all-groups") == 2
    assert command_log.count("mkcert:-install") == 2
    assert sum(line.startswith("mkcert:-cert-file ") for line in command_log) == 1


def test_setup_propagates_locked_sync_failure_before_hooks_or_trust(tmp_path: Path) -> None:
    """Setupがauthoritative lock不整合を無視せず後続side effectを止めるcontractを検証する.

    Fake uvからlock artifactを示すfailureを返し、同じexit statusとdiagnosticがpublic recipeから
    観測され、hook installationとtrust変更へ進まないことを確認する.

    Args:
        tmp_path (Path): 隔離Git repositoryとfailure fakeを置くtemporary directory.

    Returns:
        None: Locked sync failureのexit propagationとfail-fast behaviorを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'uv:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        echo 'uv.lock is not synchronized with workspace manifests' >&2
        exit 37
        """,
    )

    result = _run_just(repository_root, environment, "setup")

    assert result.returncode == 37
    assert "uv.lock" in result.stderr
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert command_log == [
        f"uv:sync --project {repository_root} --locked --all-groups",
    ]
    assert not (repository_root / ".state" / "hooks").exists()
    assert not (repository_root / ".state" / "certs" / "_wildcard.athena.localhost.pem").exists()


def test_dev_starts_core_profile_without_tunnel_configuration(tmp_path: Path) -> None:
    """Core devがCloudflare credentialなしで起動できるcontractを検証する.

    Core stateだけを持つworktreeで`dev`を実行し、Process Graphのapp、worker、Nginx entryを
    明示してoptional cloudflaredを起動対象へ含めないことを確認する.

    Args:
        tmp_path (Path): 隔離worktreeとfake Process Graph adapterを置くtemporary directory.

    Returns:
        None: Tunnel stateなしのcore development profileが成功することを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "process-compose",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'process-compose:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        if [[ "$*" == 'up' ]]; then
          echo 'bare process graph includes optional tunnel' >&2
          exit 41
        fi
        """,
    )

    result = _run_just(repository_root, environment, "dev")

    assert result.returncode == 0, result.stderr
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert command_log == ["process-compose:up app worker nginx"]


def test_dev_reports_incomplete_core_state_without_starting_processes(tmp_path: Path) -> None:
    """devが不足stateを暗黙作成せずsetup recoveryを案内するcontractを検証する.

    Setup-owned Nginx stateを欠損させて`dev`を実行し、Process Graphへ進まず現在worktreeでの
    `just setup`を案内して失敗することを確認する.

    Args:
        tmp_path (Path): 不完全なworktree stateを作るtemporary directory.

    Returns:
        None: Core preflight failureがactionableかつside-effect-freeであることを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    (repository_root / ".state" / "nginx").rmdir()
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "process-compose",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'process-compose:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        """,
    )

    result = _run_just(repository_root, environment, "dev")

    assert result.returncode != 0
    assert "just setup" in result.stderr
    assert not command_log_path.exists()


def test_dev_tunnel_requires_tunnel_setup_and_fails_without_cloudflare_config(
    tmp_path: Path,
) -> None:
    """dev-tunnelがCloudflare configを要求しcore profileを壊さないcontractを検証する.

    Core stateだけを持つworktreeでtunnel configが不足している場合に、recipeがcloudflared固有setupを
    案内してnon-zeroで終了することを確認する.

    Args:
        tmp_path (Path): 隔離worktreeを配置するtemporary directory.

    Returns:
        None: tunnel preflight未充足時にtunnel-setupを案内することを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, _ = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)

    result = _run_just(repository_root, environment, "dev-tunnel")

    assert result.returncode != 0
    stderr = result.stderr
    assert "tunnel-setup" in stderr
    assert "cloudflared/config.yml" in stderr


def test_dev_tunnel_reports_missing_origin_certificate_without_starting_processes(
    tmp_path: Path,
) -> None:
    """dev-tunnelがorigin certificate不足を起動前に報告するcontractを検証する.

    Core stateとworktree-local tunnel configだけを持つworktreeで`dev-tunnel`を実行し、
    Cloudflare account credentialを暗黙作成せず`just tunnel-setup`を案内して失敗し、
    Process Graphを開始しないことを確認する.

    Args:
        tmp_path (Path): Credential不足の隔離worktreeを配置するtemporary directory.

    Returns:
        None: Tunnel credential preflightのactionable failureを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    tunnel_config_path = repository_root / ".state" / "cloudflared" / "config.yml"
    _ = tunnel_config_path.write_text("tunnel: fixture\n", encoding="utf-8")
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "process-compose",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'process-compose:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        """,
    )

    result = _run_just(repository_root, environment, "dev-tunnel")

    assert result.returncode != 0
    assert "just tunnel-setup" in result.stderr
    assert "origin certificate" in result.stderr
    assert not command_log_path.exists()


def test_dev_tunnel_reads_worktree_local_cloudflare_config(tmp_path: Path) -> None:
    """dev-tunnelが現在worktreeのgenerated tunnel stateだけを使うcontractを検証する.

    `.state/cloudflared`配下のconfigとorigin certificateを配置し、旧root pathや別worktreeへ
    fallbackせずcore profileへcloudflared processを追加して起動することを確認する.

    Args:
        tmp_path (Path): 隔離worktreeとfake Process Graph adapterを置くtemporary directory.

    Returns:
        None: Worktree-local tunnel stateでtunnel profileが起動することを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    tunnel_config_path = repository_root / ".state" / "cloudflared" / "config.yml"
    _ = tunnel_config_path.write_text("tunnel: fixture\n", encoding="utf-8")
    origin_certificate_path = (
        tunnel_config_path.parent / "login-home" / ".cloudflared" / "cert.pem"
    )
    _ = origin_certificate_path.parent.mkdir(parents=True)
    _ = origin_certificate_path.write_text("fixture account credential\n", encoding="utf-8")
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "process-compose",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'process-compose:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        """,
    )

    result = _run_just(repository_root, environment, "dev-tunnel")

    assert result.returncode == 0, result.stderr
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert command_log == ["process-compose:up app worker nginx cloudflared"]


def test_tunnel_setup_isolated_validation_propagates_cloudflared_failure(
    tmp_path: Path,
) -> None:
    """tunnel-setupがcore setupを変更せずCloudflare failureを伝播するcontractを検証する.

    Worktree-local configとorigin certificateを用意してCloudflare validationを失敗させ、
    commandのexit statusが保持される一方で`.venv`やcore stateが暗黙生成されないことを確認する.

    Args:
        tmp_path (Path): Tunnel-only stateとfake cloudflaredを置くtemporary directory.

    Returns:
        None: Tunnel setup failureの分離とexit propagationを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    tunnel_config_path = repository_root / ".state" / "cloudflared" / "config.yml"
    _ = tunnel_config_path.parent.mkdir(parents=True)
    _ = tunnel_config_path.write_text("tunnel: fixture\n", encoding="utf-8")
    origin_certificate_path = (
        tunnel_config_path.parent / "login-home" / ".cloudflared" / "cert.pem"
    )
    _ = origin_certificate_path.parent.mkdir(parents=True)
    _ = origin_certificate_path.write_text("fixture account credential\n", encoding="utf-8")
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "cloudflared",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'cloudflared:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        echo 'fixture Cloudflare account rejected the tunnel' >&2
        exit 43
        """,
    )

    result = _run_just(repository_root, environment, "tunnel-setup")

    assert result.returncode == 43
    assert "Cloudflare account" in result.stderr
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    expected_validation_command = " ".join(
        (
            "cloudflared:tunnel",
            "--origincert",
            str(origin_certificate_path),
            "--config",
            str(tunnel_config_path),
            "list",
        )
    )
    assert command_log == [expected_validation_command]
    assert not (repository_root / ".venv").exists()
    assert not (repository_root / ".state" / "postgres").exists()


def test_tunnel_setup_initializes_worktree_local_cloudflare_credential(tmp_path: Path) -> None:
    """tunnel-setupが対話的account credentialを現在worktreeへ初期化するcontractを検証する.

    Cloudflaredと同様にfake loginが`$HOME/.cloudflared/cert.pem`へcredentialを生成し、同じ
    明示的recipe内でworktree-local configのvalidationへ進むことを確認する. Core setup stateは
    作成しない.

    Args:
        tmp_path (Path): Tunnel-only stateとfake cloudflaredを置くtemporary directory.

    Returns:
        None: Cloudflare loginとvalidationがworktree-local stateへ収束することを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    tunnel_state_path = repository_root / ".state" / "cloudflared"
    _ = tunnel_state_path.mkdir(parents=True)
    tunnel_config_path = tunnel_state_path / "config.yml"
    tunnel_login_home = tunnel_state_path / "login-home"
    origin_certificate_path = tunnel_login_home / ".cloudflared" / "cert.pem"
    _ = tunnel_config_path.write_text("tunnel: fixture\n", encoding="utf-8")
    environment["ATHENA_TEST_TUNNEL_LOGIN_HOME"] = str(tunnel_login_home)
    environment["ATHENA_TEST_ORIGIN_CERTIFICATE"] = str(origin_certificate_path)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "cloudflared",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'cloudflared:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        if [[ "$*" == 'tunnel login' ]]; then
          [[ "$HOME" == "$ATHENA_TEST_TUNNEL_LOGIN_HOME" ]]
          mkdir -p "$(dirname "$ATHENA_TEST_ORIGIN_CERTIFICATE")"
          printf 'fixture account credential\n' > "$ATHENA_TEST_ORIGIN_CERTIFICATE"
          exit 0
        fi
        expected_validation="tunnel --origincert $ATHENA_TEST_ORIGIN_CERTIFICATE"
        expected_validation+=" --config $PWD/.state/cloudflared/config.yml list"
        [[ "$*" == "$expected_validation" && -f "$ATHENA_TEST_ORIGIN_CERTIFICATE" ]]
        """,
    )

    first_result = _run_just(repository_root, environment, "tunnel-setup")
    second_result = _run_just(repository_root, environment, "tunnel-setup")

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert origin_certificate_path.is_file()
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    expected_validation_command = " ".join(
        (
            "cloudflared:tunnel",
            "--origincert",
            str(origin_certificate_path),
            "--config",
            str(tunnel_config_path),
            "list",
        )
    )
    assert command_log == [
        "cloudflared:tunnel login",
        expected_validation_command,
        expected_validation_command,
    ]
    assert not (repository_root / ".venv").exists()
    assert not (repository_root / ".state" / "postgres").exists()


def test_database_and_worktree_recipes_preserve_specialized_helper_contracts(
    tmp_path: Path,
) -> None:
    """Database operationとworktree lifecycleの既存導線をroot recipeから検証する.

    Alembicはserver workspaceから実行し、test database operationはlegacy capability ownerへ、
    worktree lifecycleはspecialized helperへargumentとexit statusを変えずに委譲する.

    Args:
        tmp_path (Path): Fake delegate scriptsとcommand logを置くtemporary directory.

    Returns:
        None: 各public recipeのargument forwardingとfailure propagationを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'uv:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        exit 31
        """,
    )
    _write_executable(
        repository_root / "scripts" / "dev-tasks.sh",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'dev-tasks:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        exit 23
        """,
    )
    _write_executable(
        repository_root / "scripts" / "agent-worktree.sh",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'agent-worktree:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        exit 29
        """,
    )

    migration_result = _run_just(repository_root, environment, "db-migrate")
    database_results = {
        recipe: _run_just(repository_root, environment, recipe)
        for recipe in ("db-test-create", "db-test-migrate", "db-test-run")
    }
    worktree_result = _run_just(
        repository_root,
        environment,
        "worktree",
        "fixture-task",
        "--agent",
        "codex",
    )

    assert migration_result.returncode == 31
    assert all(result.returncode == 23 for result in database_results.values())
    assert worktree_result.returncode == 29
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert command_log == [
        f"uv:run --directory {repository_root}/apps/athena_server alembic upgrade head",
        "dev-tasks:db:test:create",
        "dev-tasks:db:test:migrate",
        "dev-tasks:db:test:run",
        "agent-worktree:fixture-task --agent codex",
    ]


def test_public_recipe_catalog_exposes_root_workflows(tmp_path: Path) -> None:
    """Root task catalogがTask 3.2のpublic workflowを発見可能にするcontractを検証する.

    Args:
        tmp_path (Path): Public justfileを置くisolated repository directory.

    Returns:
        None: Setup、development、validation、database、audit、worktree recipeを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)

    result = subprocess.run(
        [
            "just",
            "--justfile",
            str(repository_root / "justfile"),
            "--list",
            "--unsorted",
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    for recipe_name in (
        "setup",
        "tunnel-setup",
        "dev",
        "dev-tunnel",
        "quality",
        "docstrings",
        "test",
        "build",
        "db-migrate",
        "db-test-create",
        "db-test-migrate",
        "db-test-run",
        "ci",
        "audit-monorepo",
        "worktree",
    ):
        assert f"    {recipe_name}" in result.stdout
