"""Worktree-local process graphとdevelopment ingressのcontractを検証するmodule."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FLAKE_PATH = REPOSITORY_ROOT / "flake.nix"
PROCESS_COMPOSE_PATH = REPOSITORY_ROOT / "process-compose.yml"
NGINX_TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "development" / "nginx" / "nginx.conf.template"
CLOUDFLARED_TEMPLATE_PATH = (
    REPOSITORY_ROOT / "infra" / "development" / "cloudflared" / "config.yml.example"
)
HOSTS_TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "development" / "hosts.example"
NGINX_TLS_PROBE_PATH = REPOSITORY_ROOT / "tools" / "monorepo_migration" / "nginx_tls_probe.py"
CORE_PROCESS_NAMES = frozenset(
    {
        "postgres",
        "postgres-init",
        "postgres-migrate",
        "valkey",
        "app",
        "worker",
        "nginx",
    }
)
RUNNING_CORE_PROCESS_NAMES = CORE_PROCESS_NAMES - {"postgres-init", "postgres-migrate"}
DEPENDENT_PROCESS_NAMES = frozenset({"app", "worker", "nginx"})
STATE_PROCESS_NAMES = frozenset({"postgres", "valkey"})
VALID_SYNTHETIC_SHUTDOWN_ORDER = (
    ("nginx", "Terminating"),
    ("nginx", "Completed"),
    ("worker", "Terminating"),
    ("app", "Terminating"),
    ("worker", "Completed"),
    ("app", "Completed"),
    ("valkey", "Terminating"),
    ("postgres", "Terminating"),
    ("valkey", "Completed"),
    ("postgres", "Completed"),
)


def _parse_yaml_scalar(raw_value: str) -> bool | int | str:
    """Process Graphで使うYAML scalarをPython valueへ変換する.

    Args:
        raw_value (str): Mapping separator以降のtrim済みscalar source.

    Returns:
        bool | int | str: Boolean、integer、またはstringへ解釈した値.
    """
    if raw_value == "true":
        return True
    if raw_value == "false":
        return False
    if raw_value.isdecimal():
        return int(raw_value)
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
        return raw_value[1:-1]
    return raw_value


def _parse_yaml_mapping(
    lines: list[str],
    start_index: int = 0,
    indentation: int = 0,
) -> tuple[dict[str, object], int]:
    """Process Composeで使用するmapping-only YAML subsetを構造化する.

    Args:
        lines (list[str]): Root process graphを行へ分割したsource.
        start_index (int): 現在のmappingを読み始めるline index.
        indentation (int): 現在のmapping keyに要求するspace数.

    Returns:
        tuple[dict[str, object], int]: Parsed mappingと次に未処理のline index.

    Raises:
        AssertionError: Mapping以外の予期しないindentationまたはsyntaxを検出した場合.

    Notes:
        このhelperは現行Process Compose graphで使うmapping、scalar、block scalarだけを扱う.
        YAML全体やProcess Compose schemaの正当性はinstalled binaryの`--dry-run` testへ委譲する.
    """
    mapping: dict[str, object] = {}
    line_index = start_index
    while line_index < len(lines):
        line = lines[line_index]
        stripped_line = line.lstrip(" ")
        if not stripped_line or stripped_line.startswith("#"):
            line_index += 1
            continue
        current_indentation = len(line) - len(stripped_line)
        if current_indentation < indentation:
            break
        assert current_indentation == indentation, (
            f"unexpected YAML indentation on line {line_index + 1}: {line!r}"
        )
        key, separator, value_source = stripped_line.partition(":")
        assert separator, f"expected YAML mapping on line {line_index + 1}: {line!r}"
        value_source = value_source.strip()
        line_index += 1
        if value_source in {">", ">-", "|", "|-"}:
            block_lines: list[str] = []
            while line_index < len(lines):
                block_line = lines[line_index]
                if not block_line.strip():
                    block_lines.append("")
                    line_index += 1
                    continue
                block_indentation = len(block_line) - len(block_line.lstrip(" "))
                if block_indentation <= current_indentation:
                    break
                block_lines.append(block_line[current_indentation + 2 :])
                line_index += 1
            mapping[key] = "\n".join(block_lines)
            continue
        if value_source:
            mapping[key] = _parse_yaml_scalar(value_source)
            continue
        nested_mapping, line_index = _parse_yaml_mapping(
            lines,
            start_index=line_index,
            indentation=current_indentation + 2,
        )
        mapping[key] = nested_mapping
    return mapping, line_index


def _load_process_graph() -> dict[str, object]:
    """Root Process Compose graphを構造化mappingとして読み込む.

    Returns:
        dict[str, object]: Top-level process graph mapping.
    """
    process_graph = PROCESS_COMPOSE_PATH.read_text(encoding="utf-8")
    mapping, next_line_index = _parse_yaml_mapping(process_graph.splitlines())
    assert next_line_index == len(process_graph.splitlines())
    return mapping


def _require_mapping(mapping: dict[str, object], key: str) -> dict[str, object]:
    """Mappingの指定keyにnested mappingが存在することを保証して返す.

    Args:
        mapping (dict[str, object]): Keyを検索するparent mapping.
        key (str): Nested mappingを要求するkey.

    Returns:
        dict[str, object]: 指定keyに格納されたnested mapping.

    Raises:
        AssertionError: Keyが存在しないかvalueがmappingではない場合.
    """
    value = mapping.get(key)
    assert isinstance(value, dict), f"expected mapping at {key!r}: {value!r}"
    return cast("dict[str, object]", value)


def _require_string(mapping: dict[str, object], key: str) -> str:
    """Mappingの指定keyにstringが存在することを保証して返す.

    Args:
        mapping (dict[str, object]): Keyを検索するmapping.
        key (str): String valueを要求するkey.

    Returns:
        str: 指定keyに格納されたstring.

    Raises:
        AssertionError: Keyが存在しないかvalueがstringではない場合.
    """
    value = mapping.get(key)
    assert isinstance(value, str), f"expected string at {key!r}: {value!r}"
    return value


def _dependency_conditions(process: dict[str, object]) -> dict[str, str]:
    """Process definitionからdependencyごとの起動conditionを返す.

    Args:
        process (dict[str, object]): `processes`直下のprocess definition.

    Returns:
        dict[str, str]: Dependency process名とconditionの対応.
    """
    raw_dependencies = process.get("depends_on")
    if raw_dependencies is None:
        return {}
    assert isinstance(raw_dependencies, dict), raw_dependencies
    dependencies = cast("dict[str, object]", raw_dependencies)
    return {
        dependency_name: _require_string(
            cast("dict[str, object]", dependency_definition),
            "condition",
        )
        for dependency_name, dependency_definition in dependencies.items()
        if isinstance(dependency_definition, dict)
    }


def _tracked_worktreeinclude_entries() -> set[str]:
    """`.worktreeinclude`から有効なcopy対象pathを返す.

    Returns:
        set[str]: コメントと空行を除いたrepository-root relative pathの集合.
    """
    worktreeinclude_path = REPOSITORY_ROOT / ".worktreeinclude"
    return {
        line
        for raw_line in worktreeinclude_path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    }


def _git_ignored_paths(paths: set[str]) -> set[str]:
    """指定したpathのうちGit ignore対象として扱われるものを返す.

    Args:
        paths (set[str]): repository rootから見たignore確認対象path.

    Returns:
        set[str]: `git check-ignore`がignore対象として返したpath集合.
    """
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "check-ignore", "--stdin"],
        check=False,
        capture_output=True,
        input="\n".join(sorted(paths)) + "\n",
        text=True,
    )
    assert result.returncode in {0, 1}, result.stderr
    return set(result.stdout.splitlines())


def _fingerprint_environment_entry_path(
    path: Path,
) -> tuple[tuple[str, str, int, int, int, int, str], ...]:
    """Environment entryの明示対象pathをmetadata snapshotへ変換する.

    Args:
        path (Path): `.venv`、`.state`、hook、certificate、CAROOTのいずれかのpath.

    Returns:
        tuple[tuple[str, str, int, int, int, int, str], ...]: Relative path、kind、mode、
            size、mtime、inode、symlink targetから成る安定順のentry列.
    """
    if not path.exists() and not path.is_symlink():
        return ((".", "missing", 0, 0, 0, 0, ""),)
    candidates = [path]
    if path.is_dir() and not path.is_symlink():
        candidates.extend(path.rglob("*"))
    entries: list[tuple[str, str, int, int, int, int, str]] = []
    for candidate in sorted(candidates, key=lambda item: item.as_posix()):
        metadata = candidate.lstat()
        relative_path = "." if candidate == path else candidate.relative_to(path).as_posix()
        if candidate.is_symlink():
            kind = "symlink"
            target = str(candidate.readlink())
        elif candidate.is_dir():
            kind = "directory"
            target = ""
        elif candidate.is_file():
            kind = "file"
            target = ""
        else:
            kind = "other"
            target = ""
        entries.append(
            (
                relative_path,
                kind,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ino,
                target,
            )
        )
    return tuple(entries)


def _environment_entry_snapshot(isolated_caroot: Path) -> dict[str, object]:
    """Environment entryが不変に保つrepository/worktree stateを返す.

    Args:
        isolated_caroot (Path): Trust-state mutationを隔離して検出するCAROOT path.

    Returns:
        dict[str, object]: Source diff/status、Git hook config、明示対象path fingerprintのmapping.
    """
    source_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    source_diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    hook_configuration = subprocess.run(
        [
            "git",
            "config",
            "--show-origin",
            "--get-regexp",
            "^(core\\.hookspath|extensions\\.worktreeconfig)$",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert hook_configuration.returncode in {0, 1}, hook_configuration.stderr
    explicit_paths = {
        "virtual-environment": REPOSITORY_ROOT / ".venv",
        "runtime-state": REPOSITORY_ROOT / ".state",
        "hook-config": REPOSITORY_ROOT / ".pre-commit-config.yaml",
        "hook-files": REPOSITORY_ROOT / ".state" / "hooks",
        "certificates": REPOSITORY_ROOT / ".state" / "certs",
        "isolated-caroot": isolated_caroot,
    }
    return {
        "source-status": source_status,
        "source-diff": source_diff,
        "hook-configuration": (hook_configuration.returncode, hook_configuration.stdout),
        "paths": {
            label: _fingerprint_environment_entry_path(path)
            for label, path in explicit_paths.items()
        },
    }


def _replace_exactly_once(source: str, old: str, new: str, label: str) -> str:
    """Fixture source内のexpected fragmentを1回だけ置換する.

    Args:
        source (str): 置換前のtracked source.
        old (str): 1回だけ存在することを要求するfragment.
        new (str): Fixtureへ書き込むreplacement fragment.
        label (str): Contract drift時のdiagnosticに使う対象名.

    Returns:
        str: 指定fragmentを置換したfixture source.

    Raises:
        AssertionError: Expected fragmentの出現回数が1回ではない場合.
    """
    occurrence_count = source.count(old)
    assert occurrence_count == 1, (
        f"{label} fixture expected exactly one {old!r}, found {occurrence_count}"
    )
    return source.replace(old, new)


def _allocate_loopback_ports(names: tuple[str, ...]) -> dict[str, int]:
    """同時に予約したloopback socketから重複しないephemeral portを割り当てる.

    Args:
        names (tuple[str, ...]): Portを必要とするruntime endpoint名.

    Returns:
        dict[str, int]: Endpoint名とOSが割り当てたunprivileged portの対応.

    Notes:
        Socketは全portを決定するまで保持し、返却直前に解放する. Process Graph起動までの短い
        raceは残るが、固定portによる別worktreeやhost serviceとの衝突を避ける.
    """
    reserved_sockets: list[socket.socket] = []
    try:
        for _name in names:
            reserved_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            reserved_socket.bind(("127.0.0.1", 0))
            reserved_sockets.append(reserved_socket)
        return {
            name: cast("tuple[str, int]", reserved_socket.getsockname())[1]
            for name, reserved_socket in zip(names, reserved_sockets, strict=True)
        }
    finally:
        for reserved_socket in reserved_sockets:
            reserved_socket.close()


def _prepare_core_graph_state(
    repository_root: Path,
    ports: dict[str, int],
) -> Path:
    """実Process Graph用のworktree-local stateとisolated CAを準備する.

    Args:
        repository_root (Path): `.state`とprobe helperを配置するtemporary worktree root.
        ports (dict[str, int]): App、HTTP、HTTPS endpointへ割り当てたport mapping.

    Returns:
        Path: Generated server certificateを発行したisolated root CA path.
    """
    state_root = repository_root / ".state"
    nginx_state = state_root / "nginx"
    certificate_state = state_root / "certs"
    for directory in (
        state_root / "postgres",
        state_root / "valkey",
        state_root / "logs",
        state_root / "blobs",
        nginx_state / "client-body",
        nginx_state / "proxy",
        nginx_state / "fastcgi",
        nginx_state / "uwsgi",
        nginx_state / "scgi",
        certificate_state,
    ):
        directory.mkdir(parents=True)

    nginx_source = NGINX_TEMPLATE_PATH.read_text(encoding="utf-8")
    nginx_source = _replace_exactly_once(
        nginx_source,
        "listen 80;",
        f"listen {ports['http']};",
        "Nginx HTTP listener",
    )
    nginx_source = _replace_exactly_once(
        nginx_source,
        "listen 443 ssl;",
        f"listen {ports['https']} ssl;",
        "Nginx HTTPS listener",
    )
    nginx_source = _replace_exactly_once(
        nginx_source,
        "proxy_pass http://127.0.0.1:8000;",
        f"proxy_pass http://127.0.0.1:{ports['app']};",
        "Nginx app upstream",
    )
    _ = (nginx_state / "nginx.conf").write_text(nginx_source, encoding="utf-8")

    probe_path = repository_root / "tools" / "monorepo_migration" / "nginx_tls_probe.py"
    probe_path.parent.mkdir(parents=True)
    _ = shutil.copy2(NGINX_TLS_PROBE_PATH, probe_path)

    certificate_path = certificate_state / "_wildcard.athena.localhost.pem"
    certificate_key_path = certificate_state / "_wildcard.athena.localhost-key.pem"
    certificate_authority_root = repository_root / "mkcert-ca"
    mkcert_path = shutil.which("mkcert")
    assert mkcert_path is not None, "mkcert must be available in the Nix development shell"
    certificate_environment = os.environ.copy()
    certificate_environment["CAROOT"] = str(certificate_authority_root)
    certificate_result = _run_captured_command(
        [
            mkcert_path,
            "-cert-file",
            str(certificate_path),
            "-key-file",
            str(certificate_key_path),
            "*.athena.localhost",
        ],
        environment=certificate_environment,
        timeout_seconds=30,
        working_directory=repository_root,
    )
    assert certificate_result.returncode == 0, certificate_result.stderr
    return certificate_authority_root / "rootCA.pem"


def _core_graph_environment(
    repository_root: Path,
    ports: dict[str, int],
    certificate_authority_root: Path,
) -> dict[str, str]:
    """Credentialを含まないisolated core Process Graph environmentを返す.

    Args:
        repository_root (Path): Runtime stateを所有するtemporary worktree root.
        ports (dict[str, int]): 各runtime endpointへ割り当てたport mapping.
        certificate_authority_root (Path): `mkcert -CAROOT`へ公開するisolated CA directory.

    Returns:
        dict[str, str]: Real PostgreSQL、Valkey、app、worker、Nginx用subprocess environment.
    """
    database_user = os.environ.get("USER") or os.environ.get("LOGNAME")
    assert database_user, "current database user must be available"
    state_root = repository_root / ".state"
    environment = os.environ.copy()
    environment.update(
        {
            "ATHENA_NGINX_TLS_PORT": str(ports["https"]),
            "ATHENA_STATE": str(state_root),
            "ATHENA_WORKTREE_ROOT": str(repository_root),
            "BEATMAP_OFFICIAL_SOURCES_ENABLED": "false",
            "BLOB_STORAGE_BACKEND": "local",
            "BLOB_STORAGE_LOCAL_ROOT": str(state_root / "blobs"),
            "CAROOT": str(certificate_authority_root),
            "DATABASE_URL": (
                "postgresql+asyncpg://"
                f"{quote(database_user, safe='')}@127.0.0.1:{ports['postgres']}/athena"
            ),
            "DOMAIN": "athena.localhost",
            "ENVIRONMENT": "development",
            "LOG_DIR": str(state_root / "logs"),
            "PGDATA": str(state_root / "postgres"),
            "PGHOST": "127.0.0.1",
            "PGPORT": str(ports["postgres"]),
            "PGUSER": database_user,
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(ports["app"]),
            "VALKEY_PORT": str(ports["valkey"]),
            "VALKEY_URL": f"redis://127.0.0.1:{ports['valkey']}/0",
        }
    )
    return environment


def _run_captured_command(
    command: list[str],
    *,
    environment: dict[str, str],
    timeout_seconds: float,
    working_directory: Path = REPOSITORY_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Runtime検証commandを共通のcaptured subprocess contractで実行する.

    Args:
        command (list[str]): 実行するexecutableとarguments.
        environment (dict[str, str]): Child processへ渡すenvironment.
        timeout_seconds (float): Command完了を待機する最大秒数.
        working_directory (Path): Child processのcurrent working directory.

    Returns:
        subprocess.CompletedProcess[str]: Text modeでstdout/stderrをcaptureした終了結果.

    Raises:
        OSError: Child processを起動できない場合.
        subprocess.TimeoutExpired: Commandがtimeoutまでに完了しない場合.
    """
    return subprocess.run(
        command,
        cwd=working_directory,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=timeout_seconds,
    )


def _process_compose_client(socket_path: Path, *arguments: str) -> list[str]:
    """指定UDSのProcess Compose serverへ接続するcommandを返す.

    Args:
        socket_path (Path): Isolated Process Compose serverのUnix socket path.
        *arguments (str): Serverへ送るsubcommandとargument.

    Returns:
        list[str]: `subprocess`へ渡せるProcess Compose client command.
    """
    return ["process-compose", "-U", "-u", str(socket_path), *arguments]


def _start_process_compose_graph(
    socket_path: Path,
    log_path: Path,
    process_names: tuple[str, ...],
    environment: dict[str, str],
) -> None:
    """指定processを含むisolated Process Compose graphをdetached起動する.

    Args:
        socket_path (Path): Process Compose serverのUnix socket path.
        log_path (Path): Process Compose server logの出力先.
        process_names (tuple[str, ...]): Dependencyを含めて起動するtarget process名.
        environment (dict[str, str]): Graphへ渡すruntime environment.

    Returns:
        None: Detached起動commandの成功を検証して完了する.
    """
    up_result = _run_captured_command(
        [
            "process-compose",
            "-U",
            "-u",
            str(socket_path),
            "-L",
            str(log_path),
            "--log-no-color",
            "up",
            "-D",
            "-t=false",
            "--disable-dotenv",
            "-f",
            str(PROCESS_COMPOSE_PATH),
            *process_names,
        ],
        environment=environment,
        timeout_seconds=30,
    )
    assert up_result.returncode == 0, up_result.stderr


def _process_compose_log(log_path: Path) -> str:
    """Process Compose logをfailure diagnostic用textとして返す.

    Args:
        log_path (Path): Detached Process Compose serverのlog file path.

    Returns:
        str: Log fileのUTF-8 text. Fileがまだ存在しない場合は明示的なplaceholder.
    """
    if not log_path.is_file():
        return "<process-compose log is missing>"
    return log_path.read_text(encoding="utf-8", errors="replace")


def _process_output(
    client_command: list[str],
    process_names: tuple[str, ...],
    environment: dict[str, str],
) -> str:
    """Process Composeが保持するprocess別logをdiagnostic textとして返す.

    Args:
        client_command (list[str]): Isolated UDSへ接続するProcess Compose command prefix.
        process_names (tuple[str, ...]): Logを取得するprocess名.
        environment (dict[str, str]): Process Compose clientへ渡すruntime environment.

    Returns:
        str: Process名ごとにlabelした直近200行のstdout/stderr.
    """
    sections: list[str] = []
    for process_name in process_names:
        result = _run_captured_command(
            [
                *client_command,
                "process",
                "logs",
                process_name,
                "--raw-log",
                "-n",
                "200",
            ],
            environment=environment,
            timeout_seconds=5,
        )
        output = result.stdout
        if result.stderr:
            output = f"{output}\n[client stderr]\n{result.stderr}"
        sections.append(
            f"=== {process_name} logs (exit {result.returncode}) ===\n{output.rstrip()}"
        )
    return "\n".join(sections)


def _process_states_by_name(
    client_command: list[str],
    *,
    environment: dict[str, str],
    log_path: Path,
) -> dict[str, dict[str, object]]:
    """Process Compose state snapshotをprocess名で索引して返す.

    Args:
        client_command (list[str]): Isolated UDSへ接続するProcess Compose command prefix.
        environment (dict[str, str]): Process Compose clientへ渡すruntime environment.
        log_path (Path): State取得失敗時のdiagnosticへ含めるserver log path.

    Returns:
        dict[str, dict[str, object]]: Process名と最新stateの対応.

    Raises:
        AssertionError: State取得commandまたはJSON responseが不正な場合.
        json.JSONDecodeError: Process Compose responseがJSONではない場合.
        OSError: Process Compose clientを起動できない場合.
        subprocess.TimeoutExpired: State取得commandがtimeoutした場合.
    """
    list_result = _run_captured_command(
        [*client_command, "list", "-o", "json"],
        environment=environment,
        timeout_seconds=5,
    )
    assert list_result.returncode == 0, (
        f"could not read Process Compose state: {list_result.stderr}\n"
        f"{_process_compose_log(log_path)}"
    )
    decoded_states = cast("object", json.loads(list_result.stdout))
    assert isinstance(decoded_states, list), decoded_states
    states_by_name: dict[str, dict[str, object]] = {}
    for decoded_state in cast("list[object]", decoded_states):
        if not isinstance(decoded_state, dict):
            continue
        state = cast("dict[str, object]", decoded_state)
        state_name = state.get("name")
        if isinstance(state_name, str):
            states_by_name[state_name] = state
    return states_by_name


def _wait_for_core_graph_readiness(
    client_command: list[str],
    *,
    environment: dict[str, str],
    log_path: Path,
    timeout_seconds: float,
) -> tuple[dict[str, object], ...]:
    """Core graph readinessをpollし、early-exit時はstateとlogを即時報告する.

    Args:
        client_command (list[str]): Isolated UDSへ接続するProcess Compose command prefix.
        environment (dict[str, str]): Core graphとclientが共有するruntime environment.
        log_path (Path): Failure diagnosticへ含めるProcess Compose log path.
        timeout_seconds (float): Project readinessを待機する最大秒数.

    Returns:
        tuple[dict[str, object], ...]: Ready到達時の全process state snapshot.

    Raises:
        AssertionError: Process state取得失敗、core process early-exit、またはtimeoutの場合.
    """
    deadline = time.monotonic() + timeout_seconds
    latest_states: tuple[dict[str, object], ...] = ()
    while True:
        states_by_name = _process_states_by_name(
            client_command,
            environment=environment,
            log_path=log_path,
        )
        latest_states = tuple(states_by_name.values())
        early_exit_states = {
            process_name: states_by_name[process_name]
            for process_name in RUNNING_CORE_PROCESS_NAMES
            if process_name in states_by_name
            and states_by_name[process_name].get("process_end_time")
        }
        postgres_init_state = states_by_name.get("postgres-init")
        if (
            postgres_init_state is not None
            and postgres_init_state.get("process_end_time")
            and postgres_init_state.get("exit_code") != 0
        ):
            early_exit_states["postgres-init"] = postgres_init_state
        postgres_migrate_state = states_by_name.get("postgres-migrate")
        if (
            postgres_migrate_state is not None
            and postgres_migrate_state.get("process_end_time")
            and postgres_migrate_state.get("exit_code") != 0
        ):
            early_exit_states["postgres-migrate"] = postgres_migrate_state
        assert not early_exit_states, (
            f"core Process Graph exited before readiness: {early_exit_states!r}\n"
            f"{_process_compose_log(log_path)}\n"
            f"{_process_output(client_command, tuple(sorted(CORE_PROCESS_NAMES)), environment)}"
        )

        readiness_result = _run_captured_command(
            [*client_command, "project", "is-ready"],
            environment=environment,
            timeout_seconds=5,
        )
        if readiness_result.returncode == 0:
            return latest_states
        if time.monotonic() >= deadline:
            process_output = _process_output(
                client_command,
                tuple(sorted(CORE_PROCESS_NAMES)),
                environment,
            )
            raise AssertionError(
                "\n".join(
                    (
                        f"core Process Graph did not reach readiness: {latest_states!r}",
                        _process_compose_log(log_path),
                        process_output,
                    )
                )
            )
        time.sleep(0.2)


def _wait_for_database_initialization(
    client_command: list[str],
    *,
    environment: dict[str, str],
    log_path: Path,
    timeout_seconds: float,
) -> None:
    """PostgreSQL readinessとdatabase initの正常完了を待機する.

    Args:
        client_command (list[str]): Isolated UDSへ接続するProcess Compose command prefix.
        environment (dict[str, str]): Database initialization graphのruntime environment.
        log_path (Path): Failure diagnosticへ含めるProcess Compose log path.
        timeout_seconds (float): Database initializationを待機する最大秒数.

    Returns:
        None: PostgreSQLがreadyでdatabase initがexit 0になった時点で完了する.

    Raises:
        AssertionError: State取得失敗、PostgreSQL/database init failure、またはtimeoutの場合.
    """
    deadline = time.monotonic() + timeout_seconds
    latest_states: tuple[dict[str, object], ...] = ()
    while True:
        states_by_name = _process_states_by_name(
            client_command,
            environment=environment,
            log_path=log_path,
        )
        latest_states = tuple(states_by_name.values())
        postgres_state = states_by_name.get("postgres")
        postgres_init_state = states_by_name.get("postgres-init")
        if postgres_state is not None and postgres_state.get("process_end_time"):
            raise AssertionError(
                "\n".join(
                    (
                        f"PostgreSQL exited before database initialization: {postgres_state!r}",
                        _process_compose_log(log_path),
                        _process_output(client_command, ("postgres",), environment),
                    )
                )
            )
        if postgres_init_state is not None and postgres_init_state.get("process_end_time"):
            assert postgres_init_state.get("exit_code") == 0, (
                f"database initialization failed: {postgres_init_state!r}\n"
                f"{_process_compose_log(log_path)}\n"
                f"{_process_output(client_command, ('postgres-init',), environment)}"
            )
            assert postgres_state is not None
            assert postgres_state.get("is_ready") == "Ready", postgres_state
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                "\n".join(
                    (
                        f"database initialization did not complete: {latest_states!r}",
                        _process_compose_log(log_path),
                        _process_output(
                            client_command,
                            ("postgres", "postgres-init"),
                            environment,
                        ),
                    )
                )
            )
        time.sleep(0.2)


def _prepare_core_graph_database(
    repository_root: Path,
    environment: dict[str, str],
) -> None:
    """実database init graphを起動しcanonical migrationをheadまで適用する.

    Args:
        repository_root (Path): Process Compose UDSとlogを隔離するtemporary worktree root.
        environment (dict[str, str]): PostgreSQLとAlembicが共有するruntime environment.

    Returns:
        None: Worktree-local PostgreSQLへmigration headを適用しprocessを停止して完了する.

    Raises:
        AssertionError: Database init、canonical migration、またはgraceful shutdownが失敗した場合.
    """
    socket_path = repository_root / "database-process-compose.sock"
    log_path = repository_root / "database-process-compose.log"
    client_command = _process_compose_client(socket_path)
    graph_started = False
    try:
        graph_started = True
        _start_process_compose_graph(
            socket_path,
            log_path,
            ("postgres-init",),
            environment,
        )
        _wait_for_database_initialization(
            client_command,
            environment=environment,
            log_path=log_path,
            timeout_seconds=30,
        )

        migration_result = _run_captured_command(
            ["just", "--justfile", str(REPOSITORY_ROOT / "justfile"), "db-migrate"],
            environment=environment,
            timeout_seconds=60,
        )
        assert migration_result.returncode == 0, (
            f"canonical database migration failed: {migration_result.stderr}\n"
            f"{migration_result.stdout}\n{_process_compose_log(log_path)}"
        )

        shutdown_failure = _process_compose_shutdown_failure(
            client_command,
            environment=environment,
            timeout_seconds=30,
        )
        assert shutdown_failure is None, shutdown_failure
        graph_started = False
    finally:
        if graph_started:
            shutdown_failure = _process_compose_shutdown_failure(
                client_command,
                environment=environment,
                timeout_seconds=30,
            )
            _report_cleanup_failures([shutdown_failure] if shutdown_failure is not None else [])


def _process_compose_shutdown_failure(
    client_command: list[str],
    *,
    environment: dict[str, str],
    timeout_seconds: float,
) -> str | None:
    """Process Compose graphを停止し、失敗時だけdiagnosticを返す.

    Args:
        client_command (list[str]): Isolated UDSへ接続するProcess Compose command prefix.
        environment (dict[str, str]): Process Compose clientへ渡すruntime environment.
        timeout_seconds (float): Graph停止を待機する最大秒数.

    Returns:
        str | None: 停止失敗のdiagnostic. 正常停止した場合はNone.
    """
    try:
        down_result = _run_captured_command(
            [*client_command, "down"],
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Process Compose fallback shutdown raised {error!r}"
    if down_result.returncode == 0:
        return None
    return (
        f"Process Compose fallback shutdown exited {down_result.returncode}: "
        f"{down_result.stderr}\n{down_result.stdout}"
    )


def _report_cleanup_failures(failures: list[str]) -> None:
    """Cleanup failureをprimary failureへnote追加するか単独で送出する.

    Args:
        failures (list[str]): Cleanup中に収集したfailure diagnostic.

    Returns:
        None: Failureがなければ値を返さずに完了する.

    Raises:
        AssertionError: Primary failureがなくcleanupだけが失敗した場合.
    """
    if not failures:
        return
    message = "core graph cleanup failed:\n" + "\n".join(failures)
    active_error = sys.exception()
    if active_error is not None:
        active_error.add_note(message)
        return
    raise AssertionError(message)


def _decode_monitor_events(output: bytes) -> list[dict[str, object]]:
    """Process Compose monitorのnewline-delimited JSON eventをdecodeする.

    Args:
        output (bytes): 完全なJSON event行で構成されたmonitor output.

    Returns:
        list[dict[str, object]]: 出力順を保持したtyped monitor event.

    Raises:
        AssertionError: JSON valueがmappingではない場合.
        json.JSONDecodeError: Event行がJSONではない場合.
    """
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        decoded_event = cast("object", json.loads(line))
        assert isinstance(decoded_event, dict), decoded_event
        events.append(cast("dict[str, object]", decoded_event))
    return events


def _snapshot_states(
    events: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Monitor snapshot eventをprocess名で索引して返す.

    Args:
        events (list[dict[str, object]]): 出力順のProcess Compose monitor event.

    Returns:
        dict[str, dict[str, object]]: Snapshot対象process名とstateの対応.
    """
    snapshot_events = (event for event in events if event.get("snapshot") is True)
    states = (_event_state(event) for event in snapshot_events)
    return {
        state_name: state for state in states if isinstance(state_name := state.get("name"), str)
    }


def _wait_for_initial_monitor_output(
    monitor: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
) -> bytes:
    """Core process全件のsnapshotを受信するまでbinary outputを取得する.

    Args:
        monitor (subprocess.Popen[bytes]): JSON eventをstdoutへ出すmonitor process.
        timeout_seconds (float): Core snapshot一式の待機を打ち切る秒数.

    Returns:
        bytes: Core snapshot一式と同時に取得した後続bytes.

    Raises:
        AssertionError: Monitorが全snapshot送信前に終了するかtimeoutした場合.
        json.JSONDecodeError: 完全なevent行がJSONではない場合.
        OSError: Monitor pipeからreadできない場合.
    """
    assert monitor.stdout is not None
    deadline = time.monotonic() + timeout_seconds
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        _ = selector.register(monitor.stdout, selectors.EVENT_READ)
        while True:
            last_newline_index = output.rfind(b"\n")
            complete_output = bytes(output[: last_newline_index + 1])
            snapshot_states = _snapshot_states(_decode_monitor_events(complete_output))
            if snapshot_states.keys() >= CORE_PROCESS_NAMES:
                return bytes(output)
            remaining_seconds = deadline - time.monotonic()
            assert remaining_seconds > 0, (
                "timed out waiting for core process monitor snapshots: "
                f"received={sorted(snapshot_states)}"
            )
            ready_streams = selector.select(timeout=remaining_seconds)
            assert ready_streams, (
                "timed out waiting for core process monitor snapshots: "
                f"received={sorted(snapshot_states)}"
            )
            chunk = os.read(monitor.stdout.fileno(), 65_536)
            if not chunk:
                stderr_bytes = monitor.stderr.read() if monitor.stderr is not None else b""
                stderr = stderr_bytes.decode("utf-8", errors="replace")
                raise AssertionError(
                    "; ".join(
                        (
                            "process monitor exited before all core snapshots",
                            f"received={sorted(snapshot_states)}",
                            f"stderr={stderr}",
                        )
                    )
                )
            output.extend(chunk)


def _event_state(event: dict[str, object]) -> dict[str, object]:
    """Process monitor eventからtyped state mappingを返す.

    Args:
        event (dict[str, object]): Process Compose monitorが出力したJSON event.

    Returns:
        dict[str, object]: Process名、status、timestampを含むstate mapping.
    """
    state = event.get("state")
    assert isinstance(state, dict), event
    return cast("dict[str, object]", state)


def _state_time(state: dict[str, object], field_name: str) -> datetime:
    """Process stateのRFC 3339 timestampを比較可能な値へ変換する.

    Args:
        state (dict[str, object]): Process Compose monitorのprocess state.
        field_name (str): 取得するtimestamp field名.

    Returns:
        datetime: Timezone付きprocess lifecycle timestamp.
    """
    field_value = state.get(field_name)
    assert isinstance(field_value, str), (field_name, state)
    assert field_value, (field_name, state)
    return datetime.fromisoformat(field_value)


def _cleanup_core_graph_runtime(
    client_command: list[str],
    *,
    environment: dict[str, str],
    graph_started: bool,
    monitor: subprocess.Popen[bytes] | None,
) -> None:
    """失敗経路でもgraph停止とmonitor回収を完了してfailureを報告する.

    Args:
        client_command (list[str]): Isolated Process Compose client command prefix.
        environment (dict[str, str]): Graphとclientが共有するruntime environment.
        graph_started (bool): Fallback shutdownを試みる必要があるか.
        monitor (subprocess.Popen[bytes] | None): 起動済みmonitor. 未起動ならNone.

    Returns:
        None: Cleanupを完了し、failureがなければ値を返さない.

    Raises:
        AssertionError: Primary failureがなくcleanupだけが失敗した場合.
    """
    failures: list[str] = []
    if graph_started:
        shutdown_failure = _process_compose_shutdown_failure(
            client_command,
            environment=environment,
            timeout_seconds=60,
        )
        if shutdown_failure is not None:
            failures.append(shutdown_failure)
    if monitor is not None:
        terminated_by_cleanup = monitor.poll() is None
        try:
            if terminated_by_cleanup:
                monitor.terminate()
            try:
                _output, stderr = monitor.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                monitor.kill()
                _output, stderr = monitor.communicate(timeout=10)
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append(f"process monitor cleanup raised {error!r}")
        else:
            if not terminated_by_cleanup and monitor.returncode not in {0, None}:
                decoded_stderr = stderr.decode("utf-8", errors="replace")
                failures.append(f"process monitor exited {monitor.returncode}: {decoded_stderr}")
    _report_cleanup_failures(failures)


def _run_core_graph_lifecycle(
    runtime_root: Path,
    ports: dict[str, int],
    ca_certificate_path: Path,
    environment: dict[str, str],
    socket_path: Path,
    log_path: Path,
) -> list[dict[str, object]]:
    """Core graphをreadyからshutdownまで実行してmonitor eventを返す.

    Args:
        runtime_root (Path): Worktree-local runtime stateを持つtemporary root.
        ports (dict[str, int]): Runtime endpointへ割り当てたport mapping.
        ca_certificate_path (Path): Named HTTPS検証用のisolated root CA certificate.
        environment (dict[str, str]): Core graphとclientが共有するruntime environment.
        socket_path (Path): Isolated Process Compose serverのUnix socket path.
        log_path (Path): Process Compose server logの出力先.

    Returns:
        list[dict[str, object]]: Snapshotとlive shutdown eventを出力順で保持したlist.
    """
    client_command = _process_compose_client(socket_path)
    monitor: subprocess.Popen[bytes] | None = None
    graph_started = False
    try:
        graph_started = True
        _start_process_compose_graph(
            socket_path,
            log_path,
            ("app", "worker", "nginx"),
            environment,
        )
        _ = _wait_for_core_graph_readiness(
            client_command,
            environment=environment,
            log_path=log_path,
            timeout_seconds=60,
        )
        tls_probe_result = _run_captured_command(
            [
                sys.executable,
                str(runtime_root / "tools" / "monorepo_migration" / "nginx_tls_probe.py"),
                "probe",
                str(ca_certificate_path),
                "--port",
                str(ports["https"]),
            ],
            environment=environment,
            timeout_seconds=30,
            working_directory=runtime_root,
        )
        assert tls_probe_result.returncode == 0, tls_probe_result.stderr
        assert not (runtime_root / ".state" / "cloudflared").exists()
        monitor = subprocess.Popen(
            [*client_command, "process", "monitor", "-o", "json"],
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        initial_output = _wait_for_initial_monitor_output(monitor, timeout_seconds=15)
        shutdown_failure = _process_compose_shutdown_failure(
            client_command,
            environment=environment,
            timeout_seconds=60,
        )
        assert shutdown_failure is None, shutdown_failure
        graph_started = False
        try:
            remaining_output, monitor_stderr = monitor.communicate(timeout=15)
        except subprocess.TimeoutExpired as error:
            raise AssertionError("process monitor did not stop with the graph") from error
        assert monitor.returncode == 0, monitor_stderr.decode("utf-8", errors="replace")
        monitor_output = initial_output + remaining_output
        monitor = None
        return _decode_monitor_events(monitor_output)
    finally:
        _cleanup_core_graph_runtime(
            client_command,
            environment=environment,
            graph_started=graph_started,
            monitor=monitor,
        )


def _index_live_lifecycle_events(
    events: list[dict[str, object]],
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, object]]]:
    """Live lifecycle eventをtermination/completion情報へ索引する.

    Args:
        events (list[dict[str, object]]): Snapshotを含む全Process Compose monitor event.

    Returns:
        tuple[dict[str, int], dict[str, int], dict[str, dict[str, object]]]:
            Process別termination index、completion index、completed stateの組.
    """
    termination_indices: dict[str, int] = {}
    completed_indices: dict[str, int] = {}
    completed_states: dict[str, dict[str, object]] = {}
    for event_index, event in enumerate(events):
        if event.get("snapshot") is True:
            continue
        state = _event_state(event)
        state_name = state.get("name")
        if not isinstance(state_name, str):
            continue
        if state.get("status") == "Terminating":
            _ = termination_indices.setdefault(state_name, event_index)
        if state.get("status") == "Completed":
            _ = completed_indices.setdefault(state_name, event_index)
            completed_states[state_name] = state
    return termination_indices, completed_indices, completed_states


def _assert_core_graph_lifecycle(
    events: list[dict[str, object]],
    runtime_root: Path,
) -> None:
    """Core graphのdependency順、graceful停止、worker hook完了を検証する.

    Args:
        events (list[dict[str, object]]): Snapshotとlive shutdown eventの全monitor event.
        runtime_root (Path): Structured runtime logを持つtemporary root.

    Returns:
        None: Lifecycle contractを検証しdiagnosticを表示して完了する.
    """
    snapshot_states = _snapshot_states(events)
    assert snapshot_states.keys() >= CORE_PROCESS_NAMES
    for process_name in RUNNING_CORE_PROCESS_NAMES:
        assert snapshot_states[process_name]["is_running"] is True
    assert snapshot_states["postgres-init"]["status"] == "Completed"
    assert snapshot_states["postgres-init"]["exit_code"] == 0
    assert snapshot_states["postgres-migrate"]["status"] == "Completed"
    assert snapshot_states["postgres-migrate"]["exit_code"] == 0
    startup_times = {
        "postgres-ready": _state_time(snapshot_states["postgres"], "process_ready_time"),
        "valkey-ready": _state_time(snapshot_states["valkey"], "process_ready_time"),
        "postgres-init-start": _state_time(snapshot_states["postgres-init"], "process_start_time"),
        "postgres-init-completed": _state_time(
            snapshot_states["postgres-init"], "process_end_time"
        ),
        "postgres-migrate-start": _state_time(
            snapshot_states["postgres-migrate"], "process_start_time"
        ),
        "postgres-migrate-completed": _state_time(
            snapshot_states["postgres-migrate"], "process_end_time"
        ),
        "app-start": _state_time(snapshot_states["app"], "process_start_time"),
        "worker-start": _state_time(snapshot_states["worker"], "process_start_time"),
        "nginx-start": _state_time(snapshot_states["nginx"], "process_start_time"),
    }
    assert startup_times["postgres-ready"] <= startup_times["postgres-init-start"]
    assert startup_times["postgres-init-completed"] <= startup_times["postgres-migrate-start"]
    for process_name in ("app-start", "worker-start"):
        assert startup_times["postgres-ready"] <= startup_times[process_name]
        assert startup_times["valkey-ready"] <= startup_times[process_name]
        assert startup_times["postgres-init-completed"] <= startup_times[process_name]
        assert startup_times["postgres-migrate-completed"] <= startup_times[process_name]
    termination_indices, completed_indices, completed_states = _index_live_lifecycle_events(events)
    assert termination_indices.keys() >= RUNNING_CORE_PROCESS_NAMES
    assert max(termination_indices[name] for name in DEPENDENT_PROCESS_NAMES) < min(
        termination_indices[name] for name in STATE_PROCESS_NAMES
    )
    assert completed_indices.keys() >= RUNNING_CORE_PROCESS_NAMES
    assert completed_states.keys() >= RUNNING_CORE_PROCESS_NAMES
    assert max(completed_indices[name] for name in ("app", "worker")) < min(
        termination_indices[name] for name in STATE_PROCESS_NAMES
    ), (completed_indices, termination_indices)
    processes = _require_mapping(_load_process_graph(), "processes")
    for process_name in RUNNING_CORE_PROCESS_NAMES:
        completed_state = completed_states[process_name]
        assert termination_indices[process_name] < completed_indices[process_name], (
            process_name,
            completed_state,
        )
        assert completed_state.get("status") == "Completed", (process_name, completed_state)
        assert completed_state.get("is_running") is False, (process_name, completed_state)
        _ = _state_time(completed_state, "process_end_time")
        shutdown = _require_mapping(_require_mapping(processes, process_name), "shutdown")
        shutdown_signal = shutdown.get("signal")
        assert isinstance(shutdown_signal, int), (process_name, shutdown)
        allowed_exit_codes = {0, 128 + shutdown_signal}
        if process_name in {"app", "worker"}:
            allowed_exit_codes.add(-1)
        assert completed_state.get("exit_code") in allowed_exit_codes, (
            process_name,
            completed_state,
        )
    log_path = runtime_root / ".state" / "logs" / "latest.jsonl"
    assert log_path.is_file(), f"structured runtime log is missing: {log_path}"
    log_events = [
        cast("dict[str, object]", json.loads(line))
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(isinstance(event, dict) for event in log_events), log_events
    assert any(event.get("event") == "worker_stopped" for event in log_events), log_events
    startup_order = [
        name for name, _timestamp in sorted(startup_times.items(), key=lambda item: item[1])
    ]
    termination_order = sorted(
        RUNNING_CORE_PROCESS_NAMES,
        key=termination_indices.__getitem__,
    )
    exit_codes = {name: completed_states[name]["exit_code"] for name in termination_order}
    print(
        "core graph lifecycle evidence: "
        + "; ".join(
            (
                f"startup={' -> '.join(startup_order)}",
                f"termination={' -> '.join(termination_order)}",
                f"exit_codes={exit_codes}",
            )
        )
    )


def _synthetic_core_graph_lifecycle_events(
    lifecycle_order: tuple[tuple[str, str], ...],
    *,
    exit_codes: dict[str, int] | None = None,
) -> list[dict[str, object]]:
    """Shutdown assertionを隔離検証するsynthetic monitor event列を返す.

    Args:
        lifecycle_order (tuple[tuple[str, str], ...]): Process名とlive statusの出力順.
        exit_codes (dict[str, int] | None): Process別Completed exit code override.

    Returns:
        list[dict[str, object]]: Ready snapshotと指定順のlive lifecycle event.
    """
    snapshots: tuple[dict[str, object], ...] = (
        {
            "name": "postgres",
            "status": "Running",
            "is_running": True,
            "process_ready_time": "2026-08-05T00:00:01+00:00",
        },
        {
            "name": "valkey",
            "status": "Running",
            "is_running": True,
            "process_ready_time": "2026-08-05T00:00:01+00:00",
        },
        {
            "name": "postgres-init",
            "status": "Completed",
            "is_running": False,
            "exit_code": 0,
            "process_start_time": "2026-08-05T00:00:02+00:00",
            "process_end_time": "2026-08-05T00:00:03+00:00",
        },
        {
            "name": "postgres-migrate",
            "status": "Completed",
            "is_running": False,
            "exit_code": 0,
            "process_start_time": "2026-08-05T00:00:03+00:00",
            "process_end_time": "2026-08-05T00:00:04+00:00",
        },
        {
            "name": "app",
            "status": "Running",
            "is_running": True,
            "process_start_time": "2026-08-05T00:00:05+00:00",
            "process_ready_time": "2026-08-05T00:00:05+00:00",
        },
        {
            "name": "worker",
            "status": "Running",
            "is_running": True,
            "process_start_time": "2026-08-05T00:00:05+00:00",
        },
        {
            "name": "nginx",
            "status": "Running",
            "is_running": True,
            "process_start_time": "2026-08-05T00:00:06+00:00",
        },
    )
    events: list[dict[str, object]] = [
        {"snapshot": True, "state": snapshot} for snapshot in snapshots
    ]
    configured_exit_codes = exit_codes or {}
    for event_index, (process_name, status) in enumerate(lifecycle_order, start=10):
        state: dict[str, object] = {
            "name": process_name,
            "status": status,
            "is_running": status != "Completed",
        }
        if status == "Completed":
            state["exit_code"] = configured_exit_codes.get(process_name, 0)
            state["process_end_time"] = f"2026-08-05T00:01:{event_index:02d}+00:00"
        events.append({"snapshot": False, "state": state})
    return events


def _write_synthetic_worker_shutdown_log(runtime_root: Path, *, stopped: bool = True) -> None:
    """Synthetic lifecycle assertion用のstructured worker logを書き込む.

    Args:
        runtime_root (Path): `.state/logs/latest.jsonl`を作成するfixture root.
        stopped (bool): `worker_stopped` eventを含めるか.

    Returns:
        None: JSONL log fixtureを作成して完了する.
    """
    log_path = runtime_root / ".state" / "logs" / "latest.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event_name = "worker_stopped" if stopped else "worker_started"
    _ = log_path.write_text(f"{json.dumps({'event': event_name})}\n", encoding="utf-8")


def _assert_ingress_process_contracts(processes: dict[str, object]) -> None:
    """NginxとCloudflared processの独立起動、identity、shutdown contractを検証する.

    Args:
        processes (dict[str, object]): Root Process Composeのprocess mapping.

    Returns:
        None: Ingress process definitionを検証して完了し、呼び出し側へ値を返さない.
    """
    nginx = _require_mapping(processes, "nginx")
    nginx_command = _require_string(nginx, "command")
    assert ".state/nginx/nginx.conf" in nginx_command
    assert "sudo" not in nginx_command
    assert "sysctl" not in nginx_command
    assert _dependency_conditions(nginx) == {}
    assert "readiness_probe" not in nginx
    assert _require_mapping(nginx, "shutdown") == {
        "signal": 3,
        "timeout_seconds": 5,
    }

    cloudflared = _require_mapping(processes, "cloudflared")
    cloudflared_command = _require_string(cloudflared, "command")
    assert ".state/cloudflared/config.yml" in cloudflared_command
    assert ".state/cloudflared/login-home/.cloudflared/cert.pem" in cloudflared_command
    assert ".state/cloudflared/credentials.json" in cloudflared_command
    assert "infra/development/validate_state.py" in cloudflared_command
    assert "tunnel-id" in cloudflared_command
    assert '"$tunnel_id"' in cloudflared_command
    assert cloudflared_command.index("run") < cloudflared_command.index("--credentials-file")
    assert cloudflared_command.index("--credentials-file") < cloudflared_command.index(
        '"$tunnel_id"'
    )
    assert _dependency_conditions(cloudflared) == {}
    assert _require_mapping(cloudflared, "shutdown") == {
        "signal": 15,
        "timeout_seconds": 35,
    }


def test_development_templates_have_canonical_infra_ownership() -> None:
    """Tracked ingress sourceを`infra/development`だけが所有するcontractを検証する.

    Canonical Nginx、Cloudflared、hosts templateがdevelopment infra配下に存在し、移管前の
    root pathがsource of truthとして残らないことを確認する.

    Returns:
        None: Tracked template ownershipを検証して完了し、呼び出し側へ値を返さない.
    """
    for template_path in (
        NGINX_TEMPLATE_PATH,
        CLOUDFLARED_TEMPLATE_PATH,
        HOSTS_TEMPLATE_PATH,
    ):
        assert template_path.is_file(), template_path

    for legacy_template_path in (
        REPOSITORY_ROOT / "nginx.dev.conf.example",
        REPOSITORY_ROOT / "cloudflared" / "config.yml.example",
        REPOSITORY_ROOT / "hosts.example",
    ):
        assert not legacy_template_path.exists(), legacy_template_path


def test_worktreeinclude_entries_are_ignored_local_state_sources() -> None:
    """Worktreeへ引き継ぐlocal stateがGit追跡外のcopy対象であることを検証する.

    実osu!stable client検証とagent onboarding短縮に必要なlocal env、runtime state、
    agent cache、blob dataをworktree copy対象にしつつ、Git追跡対象にはしないことを確認する.

    Returns:
        None: Worktree include policyを検証して完了し、呼び出し側へ値を返さない.
    """
    expected_entries = {
        ".env.development",
        ".env.test",
        ".pre-commit-config.yaml",
        ".state/",
        ".serena/",
        ".gitnexus/",
        "apps/athena_server/.data/",
        "apps/athena_server/.env.development",
        "apps/athena_server/.env.test",
    }
    assert _tracked_worktreeinclude_entries() == expected_entries
    assert _git_ignored_paths(expected_entries) == expected_entries


def test_development_postgres_includes_current_paradedb_and_pgvector() -> None:
    """Development PostgreSQLがParadeDBとpgvectorを同じNix環境に含むことを検証する.

    osu!direct検索で使うpg_searchをParadeDB公式flake由来の0.25.1に固定し、後続のvector検索で
    使うpgvectorも同じPostgreSQL 18 package setへ含める契約を確認する.

    Returns:
        None: flakeのPostgreSQL extension構成を検証して完了する.
    """
    flake = FLAKE_PATH.read_text(encoding="utf-8")

    assert 'url = "github:paradedb/paradedb/v0.25.1"' in flake
    assert "pkgs.postgresql_18.withPackages" in flake
    assert 'pkgs.callPackage "${paradedb}/nix/pg_search.nix"' in flake
    assert 'version = "0.19.0";' in flake
    assert "ps.pgvector" in flake


def test_process_graph_preserves_core_readiness_dependency_and_shutdown() -> None:
    """Core graphのreadiness、dependency、ordered shutdown contractを検証する.

    PostgreSQL、idempotent database init、Valkey、app、worker、Nginxの起動順を確認し、
    ingress processがapp restartへ巻き込まれない独立processであることを確認する.

    Returns:
        None: Process lifecycle contractを検証して完了し、呼び出し側へ値を返さない.
    """
    process_graph = _load_process_graph()
    assert process_graph["ordered_shutdown"] is True
    processes = _require_mapping(process_graph, "processes")
    assert set(processes) == {
        "postgres",
        "postgres-init",
        "postgres-migrate",
        "valkey",
        "app",
        "worker",
        "nginx",
        "cloudflared",
    }

    postgres = _require_mapping(processes, "postgres")
    assert "shared_preload_libraries = 'pg_search'" in _require_string(postgres, "command")
    postgres_readiness = _require_mapping(postgres, "readiness_probe")
    assert "pg_isready" in _require_string(
        _require_mapping(postgres_readiness, "exec"),
        "command",
    )
    assert "-d postgres" in _require_string(
        _require_mapping(postgres_readiness, "exec"),
        "command",
    )
    assert _require_mapping(postgres, "shutdown") == {
        "signal": 2,
        "timeout_seconds": 30,
    }

    postgres_init = _require_mapping(processes, "postgres-init")
    assert _dependency_conditions(postgres_init) == {"postgres": "process_healthy"}
    postgres_init_command = _require_string(postgres_init, "command")
    assert "SELECT 1 FROM pg_database" in postgres_init_command
    assert "createdb" in postgres_init_command
    assert "|| true" not in postgres_init_command
    assert _require_mapping(postgres_init, "availability") == {"restart": "no"}

    postgres_migrate = _require_mapping(processes, "postgres-migrate")
    assert _dependency_conditions(postgres_migrate) == {
        "postgres": "process_healthy",
        "postgres-init": "process_completed_successfully",
    }
    postgres_migrate_command = _require_string(postgres_migrate, "command")
    assert "alembic upgrade head" in postgres_migrate_command
    assert _require_mapping(postgres_migrate, "availability") == {"restart": "no"}

    valkey = _require_mapping(processes, "valkey")
    valkey_readiness = _require_mapping(valkey, "readiness_probe")
    valkey_readiness_command = _require_string(
        _require_mapping(valkey_readiness, "exec"),
        "command",
    )
    assert "valkey-cli" in valkey_readiness_command
    assert "VALKEY_PORT" in valkey_readiness_command
    assert ":-6379" in valkey_readiness_command
    assert _require_mapping(valkey, "shutdown") == {
        "signal": 15,
        "timeout_seconds": 10,
    }

    expected_runtime_dependencies = {
        "postgres": "process_healthy",
        "postgres-init": "process_completed_successfully",
        "postgres-migrate": "process_completed_successfully",
        "valkey": "process_healthy",
    }
    app = _require_mapping(processes, "app")
    assert _dependency_conditions(app) == expected_runtime_dependencies
    assert _require_mapping(app, "shutdown") == {
        "signal": 15,
        "timeout_seconds": 30,
    }

    worker = _require_mapping(processes, "worker")
    assert _dependency_conditions(worker) == expected_runtime_dependencies
    assert _require_mapping(worker, "shutdown") == {
        "signal": 15,
        "timeout_seconds": 30,
    }

    _assert_ingress_process_contracts(processes)


def test_lifecycle_assertion_allows_app_shutdown_before_nginx_completion(
    tmp_path: Path,
) -> None:
    """Nginx完了前にapp停止が始まるevent列を独立processの正常順序として受理する.

    Args:
        tmp_path (Path): Synthetic structured worker logを配置するtemporary root.

    Returns:
        None: Ingressとappがstate serviceより先に停止し、appのunknown sentinelも
            成功扱いになることを検証して完了する.
    """
    lifecycle_order = (
        ("nginx", "Terminating"),
        ("app", "Terminating"),
        ("nginx", "Completed"),
        ("worker", "Terminating"),
        ("worker", "Completed"),
        ("app", "Completed"),
        ("valkey", "Terminating"),
        ("postgres", "Terminating"),
        ("valkey", "Completed"),
        ("postgres", "Completed"),
    )
    _write_synthetic_worker_shutdown_log(tmp_path)

    _assert_core_graph_lifecycle(
        _synthetic_core_graph_lifecycle_events(lifecycle_order, exit_codes={"app": -1}),
        tmp_path,
    )


def test_lifecycle_assertion_rejects_state_shutdown_before_runtime_completion(
    tmp_path: Path,
) -> None:
    """Appとworker完了前にstate serviceを停止するevent列を拒否する.

    Args:
        tmp_path (Path): Synthetic structured worker logを配置するtemporary root.

    Returns:
        None: Runtime completion barrier違反がAssertionErrorになることを検証して完了する.
    """
    invalid_order = (
        ("nginx", "Terminating"),
        ("nginx", "Completed"),
        ("worker", "Terminating"),
        ("app", "Terminating"),
        ("valkey", "Terminating"),
        ("worker", "Completed"),
        ("app", "Completed"),
        ("postgres", "Terminating"),
        ("valkey", "Completed"),
        ("postgres", "Completed"),
    )
    _write_synthetic_worker_shutdown_log(tmp_path)

    with pytest.raises(AssertionError):
        _assert_core_graph_lifecycle(
            _synthetic_core_graph_lifecycle_events(invalid_order),
            tmp_path,
        )


def test_lifecycle_assertion_rejects_unknown_infra_exit_code(tmp_path: Path) -> None:
    """Process Composeのunknown exit sentinelをinfra processでは拒否する.

    Args:
        tmp_path (Path): Synthetic structured worker logを配置するtemporary root.

    Returns:
        None: Nginxのexit code `-1`がAssertionErrorになることを検証して完了する.
    """
    _write_synthetic_worker_shutdown_log(tmp_path)

    with pytest.raises(AssertionError):
        _assert_core_graph_lifecycle(
            _synthetic_core_graph_lifecycle_events(
                VALID_SYNTHETIC_SHUTDOWN_ORDER,
                exit_codes={"nginx": -1},
            ),
            tmp_path,
        )


def test_lifecycle_assertion_requires_worker_stopped_for_unknown_worker_exit(
    tmp_path: Path,
) -> None:
    """Workerのunknown exit sentinelをstructured shutdown evidenceに限定する.

    Args:
        tmp_path (Path): Synthetic structured worker logを配置するtemporary root.

    Returns:
        None: Markerなしを拒否し、`worker_stopped`付きevent列だけを受理して完了する.
    """
    events = _synthetic_core_graph_lifecycle_events(
        VALID_SYNTHETIC_SHUTDOWN_ORDER,
        exit_codes={"worker": -1},
    )
    _write_synthetic_worker_shutdown_log(tmp_path, stopped=False)
    with pytest.raises(AssertionError):
        _assert_core_graph_lifecycle(events, tmp_path)

    _write_synthetic_worker_shutdown_log(tmp_path)
    _assert_core_graph_lifecycle(events, tmp_path)


@pytest.mark.skipif(
    os.environ.get("ATHENA_RUN_PROCESS_LIFECYCLE_CHECK") != "1",
    reason="explicit development checkpoint; run `just process-lifecycle-check`",
)
@pytest.mark.skipif(
    sys.platform != "linux",
    reason="process lifecycle checkpoint requires a Linux Nix development shell",
)
@pytest.mark.development_infrastructure
def test_core_process_graph_reaches_named_https_and_stops_dependents_first(
    request: pytest.FixtureRequest,
) -> None:
    """実core graphがcredentialなしでreadyになり依存逆順で正常停止する契約を検証する.

    Worktree-local state、isolated CA、ephemeral high ports、専用UDSを使ってcanonical Process
    Compose graphのPostgreSQL、Valkey、app、worker、Nginxを実際に起動する. Snapshot timestampで
    dependency readiness後の起動を確認し、named HTTPS probe成功後のlive eventでapp、worker、
    Nginxがstate serviceより先にgraceful shutdownすることを確認する.

    Args:
        request (pytest.FixtureRequest): Short temporary runtime rootのcleanupを登録するfixture.

    Returns:
        None: Core ingress readiness、dependency order、reverse shutdownを検証して完了する.
    """
    runtime_directory = tempfile.TemporaryDirectory(prefix="athena-core-graph-", dir="/tmp")
    request.addfinalizer(runtime_directory.cleanup)
    runtime_root = Path(runtime_directory.name)
    ports = _allocate_loopback_ports(("postgres", "valkey", "app", "http", "https"))
    ca_certificate_path = _prepare_core_graph_state(runtime_root, ports)
    runtime_environment = _core_graph_environment(
        runtime_root,
        ports,
        ca_certificate_path.parent,
    )
    socket_path = runtime_root / "process-compose.sock"
    log_path = runtime_root / "process-compose.log"
    _prepare_core_graph_database(runtime_root, runtime_environment)
    events = _run_core_graph_lifecycle(
        runtime_root,
        ports,
        ca_certificate_path,
        runtime_environment,
        socket_path,
        log_path,
    )
    _assert_core_graph_lifecycle(events, runtime_root)


@pytest.mark.skipif(
    os.environ.get("ATHENA_RUN_PROCESS_LIFECYCLE_CHECK") != "1",
    reason="explicit development checkpoint; run `just process-lifecycle-check`",
)
@pytest.mark.skipif(
    sys.platform != "linux",
    reason="network namespace tool provenance requires a Linux Nix development shell",
)
@pytest.mark.development_infrastructure
def test_linux_namespace_tools_resolve_directly_from_nix_store() -> None:
    """Linux checkpointのnamespace toolがhost profileへfallbackしないことを検証する.

    Returns:
        None: `ip`と`unshare`のresolved PATH entryが直接`/nix/store`配下を指すことを確認して
            完了する.
    """
    for command_name in ("ip", "unshare"):
        command_path = shutil.which(command_name)
        assert command_path is not None, (
            f"{command_name} is missing from the Nix development shell"
        )
        assert Path(command_path).is_relative_to("/nix/store"), (
            f"{command_name} resolved through host PATH fallback: {command_path}"
        )


@pytest.mark.skipif(
    os.environ.get("ATHENA_RUN_PROCESS_LIFECYCLE_CHECK") != "1",
    reason="explicit development checkpoint; run `just process-lifecycle-check`",
)
@pytest.mark.development_infrastructure
def test_nix_environment_entry_preserves_explicit_worktree_state(tmp_path: Path) -> None:
    """実Flakeへのentryがrepository、state、hook、certificate、trustを変更しないと検証する.

    Args:
        tmp_path (Path): Isolated CAROOTとtrust-state sentinelを置くtemporary directory.

    Returns:
        None: Offlineかつlockfile非更新の`nix develop`前後が同一で、export pathだけがcurrent
            worktreeを指すことを確認して完了する.
    """
    isolated_caroot = tmp_path / "isolated-caroot"
    isolated_caroot.mkdir()
    _ = (isolated_caroot / "trust-state.sentinel").write_text(
        "environment entry must not change trust state\n",
        encoding="utf-8",
    )
    state_before = _environment_entry_snapshot(isolated_caroot)
    environment = os.environ.copy()
    incorrect_shell_values = {
        "ATHENA_WORKTREE_ROOT": str(tmp_path / "wrong-worktree"),
        "ATHENA_STATE": str(tmp_path / "wrong-state"),
        "PGDATA": str(tmp_path / "wrong-postgres"),
        "PGHOST": "wrong-postgres-host",
        "PGPORT": "6543",
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "wrong-venv"),
        "VIRTUAL_ENV": str(tmp_path / "wrong-active-venv"),
        "UV_PYTHON_PREFERENCE": "system-fallback",
    }
    environment.update(incorrect_shell_values)
    environment["CAROOT"] = str(isolated_caroot)
    caller_uv_cache = tmp_path / "caller-uv-cache"
    environment["UV_CACHE_DIR"] = str(caller_uv_cache)
    inherited_venv_bin = str(REPOSITORY_ROOT / ".venv" / "bin")
    environment["PATH"] = os.pathsep.join(
        path_entry
        for path_entry in environment["PATH"].split(os.pathsep)
        if path_entry != inherited_venv_bin
    )
    assert all(
        environment[variable_name] == incorrect_value
        for variable_name, incorrect_value in incorrect_shell_values.items()
    )
    assert inherited_venv_bin not in environment["PATH"].split(os.pathsep)
    result = subprocess.run(
        [
            "nix",
            "develop",
            "--offline",
            "--no-update-lock-file",
            "--no-write-lock-file",
            "--command",
            "bash",
            "-c",
            """
            printf 'ATHENA_EXPORT|ATHENA_WORKTREE_ROOT=%s\n' "$ATHENA_WORKTREE_ROOT"
            printf 'ATHENA_EXPORT|ATHENA_STATE=%s\n' "$ATHENA_STATE"
            printf 'ATHENA_EXPORT|PGDATA=%s\n' "$PGDATA"
            printf 'ATHENA_EXPORT|PGHOST=%s\n' "$PGHOST"
            printf 'ATHENA_EXPORT|PGPORT=%s\n' "$PGPORT"
            printf 'ATHENA_EXPORT|UV_PROJECT_ENVIRONMENT=%s\n' "$UV_PROJECT_ENVIRONMENT"
            printf 'ATHENA_EXPORT|VIRTUAL_ENV=%s\n' "$VIRTUAL_ENV"
            printf 'ATHENA_EXPORT|UV_PYTHON_PREFERENCE=%s\n' "$UV_PYTHON_PREFERENCE"
            printf 'ATHENA_EXPORT|UV_CACHE_DIR=%s\n' "$UV_CACHE_DIR"
            printf 'ATHENA_EXPORT|CAROOT=%s\n' "$CAROOT"
            printf 'ATHENA_EXPORT|PATH=%s\n' "$PATH"
            """,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    exports = dict(
        line.removeprefix("ATHENA_EXPORT|").split("=", maxsplit=1)
        for line in result.stdout.splitlines()
        if line.startswith("ATHENA_EXPORT|")
    )
    worktree_root = str(REPOSITORY_ROOT)
    assert exports["ATHENA_WORKTREE_ROOT"] == worktree_root
    assert exports["ATHENA_STATE"] == f"{worktree_root}/.state"
    assert exports["PGDATA"] == f"{worktree_root}/.state/postgres"
    assert exports["PGHOST"] == "127.0.0.1"
    assert exports["PGPORT"] == "5432"
    assert exports["UV_PROJECT_ENVIRONMENT"] == f"{worktree_root}/.venv"
    assert exports["VIRTUAL_ENV"] == f"{worktree_root}/.venv"
    assert exports["UV_PYTHON_PREFERENCE"] == "only-system"
    assert exports["UV_CACHE_DIR"] == str(caller_uv_cache)
    assert exports["CAROOT"] == str(isolated_caroot)
    assert exports["PATH"].split(os.pathsep, maxsplit=1)[0] == f"{worktree_root}/.venv/bin"
    assert _environment_entry_snapshot(isolated_caroot) == state_before


@pytest.mark.skipif(
    os.environ.get("ATHENA_RUN_PROCESS_LIFECYCLE_CHECK") != "1",
    reason="explicit development checkpoint; run `just process-lifecycle-check`",
)
@pytest.mark.development_infrastructure
def test_process_compose_installed_schema_accepts_root_graph() -> None:
    """Installed Process Composeがroot graphのschemaを受理することを検証する.

    Returns:
        None: `--dry-run`の成功と全process検出を確認して完了する.
    """
    result = subprocess.run(
        [
            "process-compose",
            "--disable-dotenv",
            "--dry-run",
            "-f",
            str(PROCESS_COMPOSE_PATH),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "8 configured processes" in result.stdout


def test_cloudflared_process_uses_validated_credential_tunnel_id(tmp_path: Path) -> None:
    """Cloudflared processがcredential内の検証済みTunnelIDを実行identityに使うcontractを検証する.

    Route-only configとは独立したvalid credentialを隔離worktreeへ置き、Process Compose
    commandをfake Cloudflaredへ渡す. Validatorが正規化したUUIDだけが`run`の最終argumentに
    なることを確認する.

    Args:
        tmp_path (Path): Validator、credential、fake Cloudflaredを配置するtemporary directory.

    Returns:
        None: Credentialをsingle source of truthとするtunnel identity wiringを検証して完了する.
    """
    process_graph = _load_process_graph()
    processes = _require_mapping(process_graph, "processes")
    cloudflared_command = _require_string(
        _require_mapping(processes, "cloudflared"),
        "command",
    )
    repository_root = tmp_path / "repository"
    validator_path = repository_root / "infra" / "development" / "validate_state.py"
    validator_path.parent.mkdir(parents=True)
    _ = shutil.copy2(
        REPOSITORY_ROOT / "infra" / "development" / "validate_state.py",
        validator_path,
    )
    credentials_path = repository_root / ".state" / "cloudflared" / "credentials.json"
    credentials_path.parent.mkdir(parents=True)
    tunnel_id = "123e4567-e89b-12d3-a456-426614174000"
    credentials = {
        "AccountTag": "fixture-account",
        "TunnelSecret": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "TunnelID": tunnel_id,
    }
    _ = credentials_path.write_text(f"{json.dumps(credentials)}\n", encoding="utf-8")
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    invocation_path = tmp_path / "cloudflared-arguments"
    cloudflared_path = binary_directory / "cloudflared"
    cloudflared_source = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" > "$ATHENA_TEST_CLOUDFLARED_ARGUMENTS"
"""
    _ = cloudflared_path.write_text(cloudflared_source, encoding="utf-8")
    _ = cloudflared_path.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "ATHENA_TEST_CLOUDFLARED_ARGUMENTS": str(invocation_path),
            "ATHENA_WORKTREE_ROOT": str(repository_root),
            "PATH": f"{binary_directory}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", "-c", cloudflared_command],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    cloudflared_arguments = invocation_path.read_text(encoding="utf-8").split()
    assert cloudflared_arguments[-1] == tunnel_id
    assert cloudflared_arguments[-3:] == [
        "--credentials-file",
        str(credentials_path),
        tunnel_id,
    ]


def test_nginx_template_routes_named_local_http_and_https_to_server() -> None:
    """Local Nginx templateがnamed ingressを同じserver upstreamへrouteするcontractを検証する.

    Wildcard local subdomainをHTTP/HTTPSで内部app upstreamへ転送し、worktree-local certificateを
    使用する一方、frontend upstreamとapex Web catch-allを追加しないことを確認する.

    Returns:
        None: Core ingress routing contractを検証して完了する.
    """
    nginx_template = NGINX_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "listen 80;" in nginx_template
    assert "listen 443 ssl;" in nginx_template
    assert nginx_template.count("server_name *.athena.localhost;") == 1
    assert nginx_template.count("proxy_pass http://127.0.0.1:8000;") == 1
    assert "../certs/_wildcard.athena.localhost.pem" in nginx_template
    assert "../certs/_wildcard.athena.localhost-key.pem" in nginx_template
    assert "server_name athena.localhost;" not in nginx_template
    assert "athena_web" not in nginx_template
    assert "frontend" not in nginx_template


def _run_nginx_tls_integration(
    tmp_path: Path,
    *,
    certificate_dns_name: str,
) -> subprocess.CompletedProcess[str]:
    """隔離namespaceの実Nginxへtracked helperでHTTP/TLS probeを実行する.

    Args:
        tmp_path (Path): Isolated Nginx state、certificate、CAを配置するtemporary directory.
        certificate_dns_name (str): Fixture server certificate SANへ設定するDNS名.

    Returns:
        subprocess.CompletedProcess[str]: Helperのcaptured outputとexit statusを含む実行結果.
    """
    command_paths = {
        command_name: shutil.which(command_name)
        for command_name in ("ip", "mkcert", "nginx", "unshare")
    }
    assert all(command_paths.values()), command_paths
    state_root = tmp_path / ".state"
    nginx_state = state_root / "nginx"
    certificate_state = state_root / "certs"
    for directory in (
        nginx_state / "client-body",
        nginx_state / "proxy",
        nginx_state / "fastcgi",
        nginx_state / "uwsgi",
        nginx_state / "scgi",
        certificate_state,
    ):
        directory.mkdir(parents=True)
    _ = shutil.copy2(NGINX_TEMPLATE_PATH, nginx_state / "nginx.conf")
    certificate_path = certificate_state / "_wildcard.athena.localhost.pem"
    certificate_key_path = certificate_state / "_wildcard.athena.localhost-key.pem"
    certificate_environment = os.environ.copy()
    certificate_environment["CAROOT"] = str(tmp_path / "mkcert-ca")
    certificate_result = subprocess.run(
        [
            str(command_paths["mkcert"]),
            "-cert-file",
            str(certificate_path),
            "-key-file",
            str(certificate_key_path),
            certificate_dns_name,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=certificate_environment,
        timeout=30,
    )
    assert certificate_result.returncode == 0, certificate_result.stderr
    ca_certificate_path = Path(certificate_environment["CAROOT"]) / "rootCA.pem"
    return subprocess.run(
        [
            str(command_paths["unshare"]),
            "--user",
            "--map-root-user",
            "--net",
            sys.executable,
            str(NGINX_TLS_PROBE_PATH),
            "integration",
            str(tmp_path),
            str(command_paths["ip"]),
            str(command_paths["nginx"]),
            str(ca_certificate_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.skipif(
    os.environ.get("ATHENA_RUN_PROCESS_LIFECYCLE_CHECK") != "1",
    reason="explicit development checkpoint; run `just process-lifecycle-check`",
)
@pytest.mark.skipif(sys.platform != "linux", reason="Linux network namespace integration test")
@pytest.mark.development_infrastructure
def test_nginx_tls_ingress_routes_health_request_to_internal_app(tmp_path: Path) -> None:
    """実Nginxのverified TLS ingressがinternal app health routeへ到達するcontractを検証する.

    Isolated user/network namespace内でloopback、fixture HTTP backend、wildcard certificate、
    tracked Nginx configを起動し、isolated mkcert CAを信頼したhostname verification付きrequestが
    80/443で同じupstreamへ正しいscheme header付きで届くことを確認する.

    Args:
        tmp_path (Path): Isolated Nginx state、certificate、CAを配置するtemporary directory.

    Returns:
        None: HTTP routingとverified TLS hostname contractを実processで検証して完了する.
    """
    result = _run_nginx_tls_integration(
        tmp_path,
        certificate_dns_name="*.athena.localhost",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    os.environ.get("ATHENA_RUN_PROCESS_LIFECYCLE_CHECK") != "1",
    reason="explicit development checkpoint; run `just process-lifecycle-check`",
)
@pytest.mark.skipif(sys.platform != "linux", reason="Linux network namespace integration test")
@pytest.mark.development_infrastructure
def test_nginx_tls_probe_rejects_certificate_for_different_hostname(tmp_path: Path) -> None:
    """Tracked TLS probeが信頼済みCA発行でもhostname不一致certificateを拒否するcontractを検証する.

    Isolated mkcert CAで別DNS名のcertificateを発行して実Nginxへ設定し、loopback IPへ接続するprobeが
    `osu.athena.localhost`のhostname verificationに失敗してnon-zeroになることを確認する.

    Args:
        tmp_path (Path): Wrong-host Nginx state、certificate、CAを配置するtemporary directory.

    Returns:
        None: TLS certificate verificationを無効化していないことを実processで検証して完了する.
    """
    result = _run_nginx_tls_integration(
        tmp_path,
        certificate_dns_name="different.example.test",
    )

    assert result.returncode != 0
    assert "certificate verify failed" in result.stderr


def test_optional_tunnel_template_uses_the_same_nginx_routing() -> None:
    """Cloudflared templateがapp portを迂回せずNginxへ接続するcontractを検証する.

    Actual configとcredentialの配置先をworktree-local `.state`として案内し、tunnel ingressが
    NginxのHTTP listenerへ接続してdirect app loopbackをcanonical routeにしないことを確認する.

    Returns:
        None: Optional tunnelとcore ingressのrouting一致を検証して完了する.
    """
    cloudflared_template = CLOUDFLARED_TEMPLATE_PATH.read_text(encoding="utf-8")
    hosts_template = HOSTS_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert ".state/cloudflared/config.yml" in cloudflared_template
    assert ".state/cloudflared/credentials.json" in cloudflared_template
    assert "YOUR_TUNNEL_UUID.json" not in cloudflared_template
    active_config_lines = {
        line.strip()
        for line in cloudflared_template.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert not any(line.startswith("tunnel:") for line in active_config_lines)
    assert not any(line.startswith("credentials-file:") for line in active_config_lines)
    assert "service: http://127.0.0.1:80" in cloudflared_template
    assert ":8000" not in cloudflared_template
    assert ":8000" not in hosts_template
    assert "athena.localhost" in hosts_template
