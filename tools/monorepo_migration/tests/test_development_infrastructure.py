"""Worktree-local process graphとdevelopment ingressのcontractを検証するmodule."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROCESS_COMPOSE_PATH = REPOSITORY_ROOT / "process-compose.yml"
NGINX_TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "development" / "nginx" / "nginx.conf.template"
CLOUDFLARED_TEMPLATE_PATH = (
    REPOSITORY_ROOT / "infra" / "development" / "cloudflared" / "config.yml.example"
)
HOSTS_TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "development" / "hosts.example"
NGINX_TLS_PROBE_PATH = REPOSITORY_ROOT / "tools" / "monorepo_migration" / "nginx_tls_probe.py"


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
    dependencies = _require_mapping(process, "depends_on")
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


def _assert_ingress_process_contracts(processes: dict[str, object]) -> None:
    """NginxとCloudflared processのreadiness、identity、shutdown contractを検証する.

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
    assert _dependency_conditions(nginx) == {"app": "process_healthy"}
    nginx_readiness = _require_mapping(nginx, "readiness_probe")
    nginx_readiness_command = _require_string(
        _require_mapping(nginx_readiness, "exec"),
        "command",
    )
    assert "tools/monorepo_migration/nginx_tls_probe.py" in nginx_readiness_command
    assert "probe" in nginx_readiness_command
    assert "mkcert -CAROOT" in nginx_readiness_command
    assert "python -c" not in nginx_readiness_command
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
    assert _dependency_conditions(cloudflared) == {"nginx": "process_healthy"}
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


def test_generated_ingress_state_is_ignored_and_not_copied_between_worktrees() -> None:
    """Generated ingress stateとcredentialをGit追跡およびworktree copyから除外する.

    `.state`を包括的にignoreし、linked worktreeへcopyする対象をuser-authored server envだけに
    限定してcertificate、actual proxy/tunnel config、credentialを共有しないことを確認する.

    Returns:
        None: Generated stateの隔離policyを検証して完了し、呼び出し側へ値を返さない.
    """
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".state/" in gitignore.splitlines()
    assert _tracked_worktreeinclude_entries() == {
        "apps/athena_server/.env.development",
        "apps/athena_server/.env.test",
    }


def test_process_graph_preserves_core_readiness_dependency_and_shutdown() -> None:
    """Core graphのreadiness、dependency、ordered shutdown contractを検証する.

    PostgreSQL、idempotent database init、Valkey、app、worker、Nginxの起動順を確認し、
    optional cloudflaredがhealthyなNginxだけへ追加依存することを確認する.

    Returns:
        None: Process lifecycle contractを検証して完了し、呼び出し側へ値を返さない.
    """
    process_graph = _load_process_graph()
    assert process_graph["ordered_shutdown"] is True
    processes = _require_mapping(process_graph, "processes")
    assert set(processes) == {
        "postgres",
        "postgres-init",
        "valkey",
        "app",
        "worker",
        "nginx",
        "cloudflared",
    }

    postgres = _require_mapping(processes, "postgres")
    postgres_readiness = _require_mapping(postgres, "readiness_probe")
    assert "pg_isready" in _require_string(
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

    valkey = _require_mapping(processes, "valkey")
    valkey_readiness = _require_mapping(valkey, "readiness_probe")
    assert "valkey-cli" in _require_string(
        _require_mapping(valkey_readiness, "exec"),
        "command",
    )
    assert _require_mapping(valkey, "shutdown") == {
        "signal": 15,
        "timeout_seconds": 10,
    }

    expected_runtime_dependencies = {
        "postgres": "process_healthy",
        "postgres-init": "process_completed_successfully",
        "valkey": "process_healthy",
    }
    app = _require_mapping(processes, "app")
    assert _dependency_conditions(app) == expected_runtime_dependencies
    app_readiness = _require_mapping(app, "readiness_probe")
    assert "127.0.0.1:8000/health" in _require_string(
        _require_mapping(app_readiness, "exec"),
        "command",
    )
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
    assert "7 configured processes" in result.stdout


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


@pytest.mark.skipif(sys.platform != "linux", reason="Linux network namespace integration test")
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


@pytest.mark.skipif(sys.platform != "linux", reason="Linux network namespace integration test")
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
