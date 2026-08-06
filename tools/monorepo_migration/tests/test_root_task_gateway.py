"""Root Task Gatewayの明示的setupとdevelopment preflight contractを検証するmodule."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
JUSTFILE_PATH = REPOSITORY_ROOT / "justfile"
SETUP_SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "setup-worktree.sh"
LEGACY_DEV_TASKS_PATH = REPOSITORY_ROOT / "scripts" / "dev-tasks.sh"
GITIGNORE_PATH = REPOSITORY_ROOT / ".gitignore"
NGINX_TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "development" / "nginx" / "nginx.conf.template"
CLOUDFLARED_TEMPLATE_PATH = (
    REPOSITORY_ROOT / "infra" / "development" / "cloudflared" / "config.yml.example"
)
STATE_VALIDATOR_PATH = REPOSITORY_ROOT / "infra" / "development" / "validate_state.py"
TEST_DATABASE_TASKS_PATH = (
    REPOSITORY_ROOT / "tools" / "monorepo_migration" / "test_database_tasks.sh"
)
VALID_TUNNEL_ID = "123e4567-e89b-12d3-a456-426614174000"
VALID_TUNNEL_SECRET = base64.b64encode(bytes(32)).decode("ascii")
VALID_TUNNEL_CREDENTIALS: dict[str, object] = {
    "AccountTag": "fixture-account",
    "TunnelSecret": VALID_TUNNEL_SECRET,
    "TunnelID": VALID_TUNNEL_ID,
}

type _GeneratedPathState = tuple[tuple[str, str, str], ...]
type _GitConfigurationRecord = tuple[str, str, str, str]


@dataclass(frozen=True, slots=True)
class _WorktreeStateSnapshot:
    """Worktree-local生成物と共有Git configurationの観測結果を保持する.

    Attributes:
        generated_paths (_GeneratedPathState): Worktree root配下の生成物fingerprint.
        effective_hooks_path (str | None): 対象worktreeで有効なcore.hooksPath.
        git_configuration (tuple[_GitConfigurationRecord, ...]): Scope、origin、key、valueを
            保持するhook関連Git configuration.
        source_status (str): Untracked fileを含むGit source status.
    """

    generated_paths: _GeneratedPathState
    effective_hooks_path: str | None
    git_configuration: tuple[_GitConfigurationRecord, ...]
    source_status: str


# Public test-only key pair for offline setup-state validation.
# Production code never imports this module.
TEST_NGINX_CERTIFICATE_BASE64 = (
    "MIIEEDCCAnigAwIBAgIRAJWNHddU8LXiqpNpshhO4BQwDQYJKoZIhvcNAQELBQAw"
    "WzEeMBwGA1UEChMVbWtjZXJ0IGRldmVsb3BtZW50IENBMRgwFgYDVQQLDA9yZXRp"
    "Y3VsbXpAbml4b3MxHzAdBgNVBAMMFm1rY2VydCByZXRpY3VsbXpAbml4b3MwHhcN"
    "MjAwMTAxMDAwMDAwWhcNNDkxMjMxMjM1OTU5WjBDMScwJQYDVQQKEx5ta2NlcnQg"
    "ZGV2ZWxvcG1lbnQgY2VydGlmaWNhdGUxGDAWBgNVBAsMD3JldGljdWxtekBuaXhv"
    "czCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAMkVcFw+vqDVYmOEAp36"
    "KEIEqCoNaW87CqaR7vrZY3a3kefif0L/poYHj6sjVZRF01GmQV5naqIhmuMnh443"
    "0WJSOQ/FrGf3jtK6j5nEzqOgISiNDsZm/I6QGkOKJj8l0P/VZSXT3kZXG/4Gokae"
    "CC3ttXgaOEF3Tp78ivSDSB0DA4CCzjRGzv2MdSnBBYzSRqTcTAqkJQf0ZMuGsozX"
    "G660jmYRvAIyR6sr5XNp24ka5YW9kyGdTrH98veuKgVwzxYNzS/7iCyF0/M88g04"
    "PCTdXiBxiEBSBr4gaL+s1Usgm+UzphBF/sVNM9hDejRZPBnu7Ube31yKtCTMtEZg"
    "X8ECAwEAAaNnMGUwDgYDVR0PAQH/BAQDAgWgMBMGA1UdJQQMMAoGCCsGAQUFBwMB"
    "MB8GA1UdIwQYMBaAFL451UHLYOKHuorzpWoCwyarA/V2MB0GA1UdEQQWMBSCEiou"
    "YXRoZW5hLmxvY2FsaG9zdDANBgkqhkiG9w0BAQsFAAOCAYEAOKvyxlWgNSI4ySeB"
    "Y71fM9BZZnmQq0x55OnTt6uQVhy1K7+jrHjNTboCukNVfwZsXg3ZEvNzQ8EBs813"
    "n6XnnUzhDjyhPOAwSU0ow8eZQqzpYLRB/Y2kDfkbsgrvi+Wi5YaJkWU16rOsPtTJ"
    "09dzU0kvKN/3EdbMMql6ydiuDSq9z96oFFw1wVkAMTu6qKW05nL3Ff9Vq5IPhFnL"
    "nxueG49GDOeGxI8PtBe/AuO7oqBosLxj6uN69EbIrwDfkv84ak+JOVp8VkeMXt2U"
    "MwiNvKuUOY4TUcxpcQhkWGi3Ra+0k2oM994jXYOlaPDT1lXpLVt7n2zULF0ekmsa"
    "8c9etGYpMDCgsSW35DARVK5d9Gquo5FeQTCWLJ1pnBqY1RhdW31/BAvj2xajpePA"
    "A+jT/LRLfpKz8hxn8CWuu+7XM5F5rfmzf6j2kGNP8c+C1rzNCqDx6SJqQU/Y5+UJ"
    "SWX3rDG1971St5gwZoLWani3AYw4oL4ALN1fDGG94Xrk/sEj"
)
TEST_NGINX_PRIVATE_KEY_BASE64 = (
    "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDJFXBcPr6g1WJj"
    "hAKd+ihCBKgqDWlvOwqmke762WN2t5Hn4n9C/6aGB4+rI1WURdNRpkFeZ2qiIZrj"
    "J4eON9FiUjkPxaxn947Suo+ZxM6joCEojQ7GZvyOkBpDiiY/JdD/1WUl095GVxv+"
    "BqJGnggt7bV4GjhBd06e/Ir0g0gdAwOAgs40Rs79jHUpwQWM0kak3EwKpCUH9GTL"
    "hrKM1xuutI5mEbwCMkerK+VzaduJGuWFvZMhnU6x/fL3rioFcM8WDc0v+4gshdPz"
    "PPINODwk3V4gcYhAUga+IGi/rNVLIJvlM6YQRf7FTTPYQ3o0WTwZ7u1G3t9cirQk"
    "zLRGYF/BAgMBAAECggEALL65yjkHE8Rv2JulNnCWOTyOjA8AdWkisVabYlPx41at"
    "X7dhoK/BJyVzFX6vGieggpR3itGB47KNI/tlmWK308ReoLEYsGjgrekoL6wg3D2z"
    "azHaRhFgJTwRMBLDeH1KgMdEMvLujOHw32mr/gFH6ipxXVieSIkLJGsnY4n8B8JA"
    "/82i+QYy4y8iZTKI3BOE5l5BJisO/7VGu90G2o5RfiW/Xg/Kxa2U26NpHYy1b6w+"
    "Jiqh3Vn0BKFPbp8HVQNV5aqxXSk/5dcuio4tZ9wzmspXR/3Xg+Y2JDE/oCAhJB/v"
    "27G6c7KXtzlOM6kF4mKCzJyauyhiJSSi46RZna0qnQKBgQDVQOcBIzWm1cSeczHg"
    "P+6prWa0G0KUGd4FOig1Ic1Uu05q9LjCaXuUjY5okjT4cDTbxiQg2gwLxhXj4zeW"
    "YWZSncD/53KsQCtdkIoTuX3mTEdCoP5wR/C8v8i5rMzQ79SxmyQEprNuQ4Z0PQ03"
    "BFLPJcQHNNiwsRpc5LzVkKuB5QKBgQDxZAtzbCCcU/bxzFCN9khEGprbVQWRxtgY"
    "g5a2eimkU0o8SRsQRv8F6nYc/nSNftDzGbka7eGBOrYMvNUXIZUlPxxSDdpJ18T6"
    "6sAI8a4rtzUoXR/MRp/uX94qtiO5V582B5/9pzkFZWLbRcnS5w/n9+dp4/WdSuXf"
    "CqzGetm4rQKBgQCbTdjuCyZXifbXLi10kxrMl2vkXrXuBaibRe9iQmu2+XHykqa7"
    "bvaBCVZc8Z2CELVuGK7W/fUn3eqzPBaPff92y0xzEauBpnnuegUUuFHoFkUPUQ/7"
    "1WiNDV6xWhcPUpojfkiM2ppyAts4a/3jw1JLacWJOgNVKqV4YVzka6d7wQKBgHZs"
    "tpFxwq3vI3+M1RhQczO2ObLRC2JxQyMDq7TqSfOsSQc6dmSN8B9e34Np8pRYWvpo"
    "7D8h5TgZLaciHQi0GQ+k3qgC08zWZnUTJhM9Pk2EHDgpN6hoHZ48uioKIYyUSC+h"
    "ngQ7PeY/zzf0DQfDBDKxlH6Gr8DzNcMu4YSeUKIhAoGBAKV12DUXOSZ5+sZFy7Y4"
    "4O4zjEZ5AXB1SfFpkn6Tx0WgRh5wg1qCi7Kf6B2Fs7V7DGRjpobitre9um9rcF2N"
    "VdloxeIMzI2TRaUvoHQI4vBUOfX3MA1+Mv9SypkhhKXN2+M1T5hAZfnHI5VTY4zc"
    "ap7Hleoebep1iQz3wzT/W+Ln"
)


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


def _serialize_tunnel_credentials(credentials: dict[str, object]) -> str:
    """Tunnel credential mappingをUTF-8 JSON file用sourceへ変換する.

    Args:
        credentials (dict[str, object]): Cloudflared credential fieldを保持するmapping.

    Returns:
        str: JSON objectと末尾改行から成るcredential file source.
    """
    return f"{json.dumps(credentials)}\n"


def _copy_root_task_gateway(repository_root: Path) -> None:
    """Root Task Gatewayを隔離repositoryへ複製する.

    Args:
        repository_root (Path): gateway fixtureを配置するrepository root.

    Returns:
        None: Public justfile、setup helper、development infra、database task helperを複製して
            完了する.
    """
    scripts_directory = repository_root / "scripts"
    scripts_directory.mkdir(parents=True)
    nginx_directory = repository_root / "infra" / "development" / "nginx"
    nginx_directory.mkdir(parents=True)
    development_infra_directory = repository_root / "infra" / "development"
    _ = shutil.copy2(JUSTFILE_PATH, repository_root / "justfile")
    _ = shutil.copy2(SETUP_SCRIPT_PATH, scripts_directory / "setup-worktree.sh")
    _ = shutil.copy2(NGINX_TEMPLATE_PATH, nginx_directory / "nginx.conf.template")
    _ = shutil.copy2(STATE_VALIDATOR_PATH, development_infra_directory / "validate_state.py")
    tooling_directory = repository_root / "tools" / "monorepo_migration"
    tooling_directory.mkdir(parents=True)
    _ = shutil.copy2(TEST_DATABASE_TASKS_PATH, tooling_directory / "test_database_tasks.sh")


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


def _pem_source(label: str, encoded_der: str) -> str:
    """Base64 DER fixtureをPEM sourceへ変換する.

    Args:
        label (str): PEM boundaryに使うcertificateまたはprivate key label.
        encoded_der (str): 改行を含まないBase64 DER payload.

    Returns:
        str: 64文字幅のpayloadとPEM boundaryを含むsource.
    """
    encoded_lines = textwrap.wrap(encoded_der, width=64)
    return "\n".join(
        (
            f"-----BEGIN {label}-----",
            *encoded_lines,
            f"-----END {label}-----",
            "",
        )
    )


def _write_test_certificate_pair(
    certificate_path: Path,
    certificate_key_path: Path,
    *,
    dns_name: str = "*.athena.localhost",
) -> None:
    """Host mkcertを使わずdeterministicなtest certificate pairを書き込む.

    Args:
        certificate_path (Path): PEM certificateを書き込むpath.
        certificate_key_path (Path): 対応するPEM private keyを書き込むpath.
        dns_name (str): Certificate SANへ保持するfixture DNS名.

    Returns:
        None: Validatorが読み込めるtest-only certificate pairを作成して完了する.

    Notes:
        Wrong-host分岐では同じbyte長のSANへ置換するためcertificate署名を再計算しない. Production
        TLS verificationではなくoffline metadataとkey-pair validationだけを対象にする
        test fixtureである.
    """
    certificate_der = base64.b64decode(TEST_NGINX_CERTIFICATE_BASE64, validate=True)
    if dns_name != "*.athena.localhost":
        assert dns_name == "wrong.example.test"
        expected_dns_name = b"*.athena.localhost"
        replacement_dns_name = dns_name.encode("ascii")
        assert len(replacement_dns_name) == len(expected_dns_name)
        assert certificate_der.count(expected_dns_name) == 1
        certificate_der = certificate_der.replace(expected_dns_name, replacement_dns_name)
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_key_path.parent.mkdir(parents=True, exist_ok=True)
    _ = certificate_path.write_text(
        _pem_source("CERTIFICATE", base64.b64encode(certificate_der).decode("ascii")),
        encoding="ascii",
    )
    _ = certificate_key_path.write_text(
        _pem_source("PRIVATE KEY", TEST_NGINX_PRIVATE_KEY_BASE64),
        encoding="ascii",
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
    certificate_fixture_path = repository_root / "fixture-certificate.pem"
    certificate_key_fixture_path = repository_root / "fixture-certificate-key.pem"
    _write_test_certificate_pair(certificate_fixture_path, certificate_key_fixture_path)
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
        cp "$ATHENA_TEST_CERTIFICATE_FIXTURE" "$certificate_file"
        cp "$ATHENA_TEST_CERTIFICATE_KEY_FIXTURE" "$certificate_key_file"
        """,
    )
    _write_executable(
        binary_directory / "sysctl",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'sysctl:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        if [[ "$*" == '-n net.ipv4.ip_unprivileged_port_start' ]]; then
          if [[ -f "$ATHENA_TEST_SYSCTL_STATE" ]]; then
            cat "$ATHENA_TEST_SYSCTL_STATE"
          else
            printf '1024\n'
          fi
          exit 0
        fi
        if [[ "$*" == '-w net.ipv4.ip_unprivileged_port_start=80' ]]; then
          printf '80\n' > "$ATHENA_TEST_SYSCTL_STATE"
          printf 'net.ipv4.ip_unprivileged_port_start = 80\n'
          exit 0
        fi
        exit 2
        """,
    )
    _write_executable(
        binary_directory / "sudo",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'sudo:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        exec "$@"
        """,
    )

    environment = os.environ.copy()
    environment.update(
        {
            "ATHENA_TEST_CERTIFICATE_FIXTURE": str(certificate_fixture_path),
            "ATHENA_TEST_CERTIFICATE_KEY_FIXTURE": str(certificate_key_fixture_path),
            "ATHENA_TEST_COMMAND_LOG": str(command_log_path),
            "ATHENA_TEST_PRE_COMMIT_CONFIG": str(pre_commit_config_path),
            "ATHENA_TEST_SYSCTL_STATE": str(repository_root / "sysctl-state"),
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


def _snapshot_generated_worktree_state(
    repository_root: Path,
) -> _WorktreeStateSnapshot:
    """Generated state、hook config、source statusをworktree単位でsnapshotする.

    Args:
        repository_root (Path): Snapshot対象のprimaryまたはlinked worktree root.

    Returns:
        _WorktreeStateSnapshot: Generated path、effective hooksPath、scope/origin付きGit
            configuration、source statusの観測結果.
    """
    entries: list[tuple[str, str, str]] = []
    for relative_root in (Path(".venv"), Path(".state"), Path(".pre-commit-config.yaml")):
        state_root = repository_root / relative_root
        if not state_root.exists() and not state_root.is_symlink():
            entries.append((relative_root.as_posix(), "missing", ""))
            continue
        candidates = [state_root]
        if state_root.is_dir() and not state_root.is_symlink():
            candidates.extend(state_root.rglob("*"))
        for candidate in sorted(candidates, key=lambda item: item.as_posix()):
            relative_path = candidate.relative_to(repository_root).as_posix()
            if candidate.is_symlink():
                entries.append((relative_path, "symlink", str(candidate.readlink())))
            elif candidate.is_dir():
                entries.append((relative_path, "directory", ""))
            elif candidate.is_file():
                entries.append(
                    (
                        relative_path,
                        "file",
                        hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    )
                )
            else:
                entries.append((relative_path, "other", ""))
    hooks_path_result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert hooks_path_result.returncode in {0, 1}, hooks_path_result.stderr
    configuration_result = subprocess.run(
        [
            "git",
            "config",
            "--show-origin",
            "--show-scope",
            "--get-regexp",
            "^(core\\.hookspath|extensions\\.worktreeconfig)$",
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert configuration_result.returncode in {0, 1}, configuration_result.stderr
    configuration_records: list[_GitConfigurationRecord] = []
    for configuration_line in configuration_result.stdout.splitlines():
        scope, origin, key_and_value = configuration_line.split("\t", maxsplit=2)
        if origin.startswith("file:"):
            origin_path = Path(origin.removeprefix("file:"))
            if not origin_path.is_absolute():
                origin_path = repository_root / origin_path
            origin = f"file:{origin_path.resolve()}"
        key, value = key_and_value.split(maxsplit=1)
        configuration_records.append((scope, origin, key, value))
    source_status = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return _WorktreeStateSnapshot(
        generated_paths=tuple(entries),
        effective_hooks_path=hooks_path_result.stdout.strip() or None,
        git_configuration=tuple(sorted(configuration_records)),
        source_status=source_status,
    )


def _worktree_configuration_origin(repository_root: Path) -> str:
    """対象worktree固有Git configuration fileのorigin表現を返す.

    Args:
        repository_root (Path): Git worktree configurationを解決するworktree root.

    Returns:
        str: `git config --show-origin`が返す`file:`付きabsolute origin.
    """
    config_path_result = subprocess.run(
        ["git", "rev-parse", "--git-path", "config.worktree"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    config_path = Path(config_path_result.stdout.strip())
    if not config_path.is_absolute():
        config_path = repository_root / config_path
    return f"file:{config_path.resolve()}"


def _assert_worktree_generated_paths_are_local(repository_root: Path) -> None:
    """Setupとtunnelが作る生成物を指定worktree内だけに保持すると検証する.

    Args:
        repository_root (Path): 生成物とexecutable hookを所有するlinked worktree root.

    Returns:
        None: 必須生成物の存在、配置、hook executable bitを検証して完了する.
    """
    expected_paths = (
        repository_root / ".venv" / "bin" / "python",
        repository_root / ".state" / "nginx" / "nginx.conf",
        repository_root / ".state" / "certs" / "_wildcard.athena.localhost.pem",
        repository_root / ".state" / "certs" / "_wildcard.athena.localhost-key.pem",
        repository_root / ".state" / "cloudflared" / "config.yml",
        repository_root / ".state" / "cloudflared" / "credentials.json",
        repository_root / ".state" / "cloudflared" / "login-home" / ".cloudflared" / "cert.pem",
        repository_root / ".state" / "hooks" / "pre-commit",
        repository_root / ".state" / "hooks" / "commit-msg",
    )
    assert all(path.exists() for path in expected_paths), expected_paths
    assert all(path.is_relative_to(repository_root) for path in expected_paths)
    for hook_name in ("pre-commit", "commit-msg"):
        hook_path = repository_root / ".state" / "hooks" / hook_name
        assert hook_path.is_file()
        assert os.access(hook_path, os.X_OK)


def _create_linked_worktree_fixture(
    primary_root: Path,
    first_worktree: Path,
    second_worktree: Path,
) -> None:
    """Root gateway fixtureをcommitし2つの実linked worktreeを作成する.

    Args:
        primary_root (Path): Common Git repositoryを所有するprimary checkout path.
        first_worktree (Path): 1つ目のlinked worktree path.
        second_worktree (Path): 2つ目のlinked worktree path.

    Returns:
        None: `git worktree add`で独立branchのlinked worktreeを2つ作成して完了する.
    """
    _copy_root_task_gateway(primary_root)
    cloudflared_directory = primary_root / "infra" / "development" / "cloudflared"
    cloudflared_directory.mkdir(parents=True)
    _ = shutil.copy2(GITIGNORE_PATH, primary_root / ".gitignore")
    _ = shutil.copy2(
        CLOUDFLARED_TEMPLATE_PATH,
        cloudflared_directory / "config.yml.example",
    )
    _initialize_git_repository(primary_root)
    for key, value in (("user.name", "Athena Test"), ("user.email", "athena@example.test")):
        _ = subprocess.run(
            ["git", "config", key, value],
            cwd=primary_root,
            check=True,
            capture_output=True,
            text=True,
        )
    for command in (
        ["git", "add", "."],
        ["git", "commit", "--quiet", "-m", "fixture"],
        ["git", "worktree", "add", "--quiet", "-b", "fixture/first", str(first_worktree)],
        [
            "git",
            "worktree",
            "add",
            "--quiet",
            "-b",
            "fixture/second",
            str(second_worktree),
        ],
    ):
        _ = subprocess.run(
            command,
            cwd=primary_root,
            check=True,
            capture_output=True,
            text=True,
        )


def _prepare_linked_worktree_tunnel_state(repository_root: Path, tunnel_id: str) -> None:
    """Production validatorが受理するworktree-local tunnel inputを作成する.

    Args:
        repository_root (Path): `.state/cloudflared`を所有するlinked worktree root.
        tunnel_id (str): Worktree固有のnon-nil UUID string.

    Returns:
        None: Route configとexecution credentialを書き込んで完了する.
    """
    tunnel_state = repository_root / ".state" / "cloudflared"
    tunnel_state.mkdir(parents=True, exist_ok=True)
    _ = shutil.copy2(
        repository_root / "infra" / "development" / "cloudflared" / "config.yml.example",
        tunnel_state / "config.yml",
    )
    credentials = dict(VALID_TUNNEL_CREDENTIALS)
    credentials["TunnelID"] = tunnel_id
    _ = (tunnel_state / "credentials.json").write_text(
        _serialize_tunnel_credentials(credentials),
        encoding="utf-8",
    )


def _linked_worktree_environment(
    worktree_root: Path,
    external_tool_root: Path,
) -> tuple[dict[str, str], Path]:
    """Repository外のfake external commandを使うsetup environmentを返す.

    Args:
        worktree_root (Path): Production setupを実行するlinked worktree root.
        external_tool_root (Path): Fake toolとcommand logを置くrepository外path.

    Returns:
        tuple[dict[str, str], Path]: Worktree用environmentとexternal command log pathの組.
    """
    external_tool_root.mkdir()
    environment, command_log_path = _fake_setup_environment(external_tool_root)
    environment["ATHENA_WORKTREE_ROOT"] = str(worktree_root)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "cloudflared",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'cloudflared:%s|HOME=%s|WORKTREE=%s\n' \
          "$*" "$HOME" "$ATHENA_WORKTREE_ROOT" >> "$ATHENA_TEST_COMMAND_LOG"
        if [[ "$*" == 'tunnel login' ]]; then
          mkdir -p "$HOME/.cloudflared"
          printf 'origin certificate for %s\n' "$ATHENA_WORKTREE_ROOT" \
            > "$HOME/.cloudflared/cert.pem"
        fi
        """,
    )
    return environment, command_log_path


def _generate_nginx_certificate(
    repository_root: Path,
    *,
    dns_name: str = "*.athena.localhost",
) -> tuple[Path, Path]:
    """指定DNS名のdeterministic Nginx test certificate pairを作成する.

    Args:
        repository_root (Path): `.state/certs`を所有するfixture repository root.
        dns_name (str): Certificate SANへ記録するDNS名.

    Returns:
        tuple[Path, Path]: 作成したcertificate pathとprivate key pathの組.
    """
    certificate_directory = repository_root / ".state" / "certs"
    certificate_directory.mkdir(parents=True, exist_ok=True)
    certificate_path = certificate_directory / "_wildcard.athena.localhost.pem"
    certificate_key_path = certificate_directory / "_wildcard.athena.localhost-key.pem"
    _write_test_certificate_pair(
        certificate_path,
        certificate_key_path,
        dns_name=dns_name,
    )
    return certificate_path, certificate_key_path


def _replace_certificate_validity(
    certificate_path: Path,
    *,
    not_before: str,
    not_after: str,
) -> None:
    """Test certificateのASN.1 UTCTime validity bytesを指定値へ置換する.

    Args:
        certificate_path (Path): Deterministic fixtureから作成したPEM certificate path.
        not_before (str): 13文字のASN.1 UTCTime形式で指定する有効開始時刻.
        not_after (str): 13文字のASN.1 UTCTime形式で指定する有効終了時刻.

    Returns:
        None: Public keyを保持したままvalidity bytesを置換して完了する.

    Notes:
        Validatorのtime-window分岐を隔離して検証するfixture helperであり、置換後のcertificate署名は
        再計算しない. Nginx key pair読込とoffline metadata decodeに必要な構造は保持する.
    """
    replacements = (not_before.encode("ascii"), not_after.encode("ascii"))
    assert all(
        len(replacement) == 13 and replacement.endswith(b"Z") and replacement[:-1].isdigit()
        for replacement in replacements
    )
    pem_lines = certificate_path.read_text(encoding="ascii").splitlines()
    encoded_certificate = "".join(line for line in pem_lines if not line.startswith("-----"))
    certificate_der = bytearray(base64.b64decode(encoded_certificate, validate=True))
    utc_time_offsets: list[int] = []
    for byte_index in range(len(certificate_der) - 14):
        if bytes(certificate_der[byte_index : byte_index + 2]) != b"\x17\r":
            continue
        value_offset = byte_index + 2
        value = bytes(certificate_der[value_offset : value_offset + 13])
        if value.endswith(b"Z") and value[:-1].isdigit():
            utc_time_offsets.append(value_offset)
    assert len(utc_time_offsets) >= 2, "certificate must contain notBefore and notAfter UTCTime"
    for value_offset, replacement in zip(utc_time_offsets[:2], replacements, strict=True):
        certificate_der[value_offset : value_offset + 13] = replacement
    encoded_lines = textwrap.wrap(base64.b64encode(certificate_der).decode("ascii"), width=64)
    _ = certificate_path.write_text(
        "\n".join(
            (
                "-----BEGIN CERTIFICATE-----",
                *encoded_lines,
                "-----END CERTIFICATE-----",
                "",
            )
        ),
        encoding="ascii",
    )


def _create_complete_core_state(repository_root: Path) -> None:
    """Core development preflightを満たす有効なworktree-local stateを作る.

    Args:
        repository_root (Path): `.venv`と`.state`を所有するfixture repository root.

    Returns:
        None: Python、state directory、hook、tracked configと有効なcertificate pairを作成する.
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
    _ = _generate_nginx_certificate(repository_root)
    nginx_config_path = repository_root / ".state" / "nginx" / "nginx.conf"
    _ = nginx_config_path.write_text(
        NGINX_TEMPLATE_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _ = (repository_root / "sysctl-state").write_text("80\n", encoding="utf-8")


def test_setup_contract_fixture_does_not_require_host_mkcert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通常contract testのsetup fixtureがhost mkcertへ依存しないことを検証する.

    Args:
        tmp_path (Path): Fake tool environmentを配置するtemporary directory.
        monkeypatch (pytest.MonkeyPatch): Host command discoveryからmkcertだけを除外するfixture.

    Returns:
        None: Deterministic certificate fixtureだけでfake setup environmentを作成して完了する.
    """
    original_which = shutil.which

    def find_command_without_mkcert(command_name: str) -> str | None:
        """mkcert以外のhost command discoveryを元実装へ委譲する.

        Args:
            command_name (str): 検索するexecutable名.

        Returns:
            str | None: mkcertならNone、それ以外はhost上のresolved path.
        """
        if command_name == "mkcert":
            return None
        return original_which(command_name)

    monkeypatch.setattr(shutil, "which", find_command_without_mkcert)
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    environment, command_log_path = _fake_setup_environment(repository_root)

    assert command_log_path.parent == repository_root
    assert "ATHENA_TEST_REAL_MKCERT" not in environment


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
    nginx_config_path = repository_root / ".state" / "nginx" / "nginx.conf"
    expected_nginx_config = NGINX_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert nginx_config_path.read_text(encoding="utf-8") == expected_nginx_config
    _ = nginx_config_path.write_text("stale generated config\n", encoding="utf-8")

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
    assert nginx_config_path.read_text(encoding="utf-8") == expected_nginx_config
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
    assert command_log.count("sudo:sysctl -w net.ipv4.ip_unprivileged_port_start=80") == 1


def test_real_linked_worktrees_isolate_setup_and_tunnel_state(tmp_path: Path) -> None:
    """実linked worktree間でsetup、runtime、certificate、tunnel、hook stateを隔離する.

    Repository外のfake external commandだけでproduction setup recipeとstate validatorを実行し、
    一方の操作がprimary checkoutまたはpeer worktreeのgenerated stateを変更しないことを確認する.

    Args:
        tmp_path (Path): Primary repository、linked worktree、external fake toolを置くdirectory.

    Returns:
        None: 2 worktreeのgenerated pathとhook configurationが各root配下に分離することを検証して
            完了する.
    """
    primary_root = tmp_path / "primary"
    first_worktree = tmp_path / "linked-first"
    second_worktree = tmp_path / "linked-second"
    primary_root.mkdir()
    _create_linked_worktree_fixture(primary_root, first_worktree, second_worktree)

    primary_before_first = _snapshot_generated_worktree_state(primary_root)
    first_before_first = _snapshot_generated_worktree_state(first_worktree)
    second_before_first = _snapshot_generated_worktree_state(second_worktree)
    first_environment, first_command_log = _linked_worktree_environment(
        first_worktree,
        tmp_path / "external-tools-first",
    )
    first_setup_result = _run_just(first_worktree, first_environment, "setup")
    _prepare_linked_worktree_tunnel_state(first_worktree, VALID_TUNNEL_ID)
    first_tunnel_result = _run_just(first_worktree, first_environment, "tunnel-setup")

    assert (first_setup_result.returncode, first_tunnel_result.returncode) == (0, 0), (
        first_setup_result.stderr,
        first_tunnel_result.stderr,
    )
    primary_after_first = _snapshot_generated_worktree_state(primary_root)
    first_after_first = _snapshot_generated_worktree_state(first_worktree)
    second_after_first = _snapshot_generated_worktree_state(second_worktree)
    expected_shared_configuration = (
        "local",
        f"file:{(primary_root / '.git' / 'config').resolve()}",
        "extensions.worktreeconfig",
        "true",
    )
    for unchanged_before, unchanged_after in (
        (primary_before_first, primary_after_first),
        (second_before_first, second_after_first),
    ):
        assert unchanged_after.generated_paths == unchanged_before.generated_paths
        assert unchanged_after.effective_hooks_path == unchanged_before.effective_hooks_path
        assert unchanged_after.source_status == unchanged_before.source_status
        assert set(unchanged_after.git_configuration) == {
            *unchanged_before.git_configuration,
            expected_shared_configuration,
        }
    expected_first_hook_configuration = (
        "worktree",
        _worktree_configuration_origin(first_worktree),
        "core.hookspath",
        str(first_worktree / ".state" / "hooks"),
    )
    assert set(first_after_first.git_configuration) - set(
        first_before_first.git_configuration
    ) == {expected_shared_configuration, expected_first_hook_configuration}

    primary_before_second = _snapshot_generated_worktree_state(primary_root)
    first_before_second = _snapshot_generated_worktree_state(first_worktree)
    second_environment, second_command_log = _linked_worktree_environment(
        second_worktree,
        tmp_path / "external-tools-second",
    )
    second_setup_result = _run_just(second_worktree, second_environment, "setup")
    _prepare_linked_worktree_tunnel_state(
        second_worktree,
        "123e4567-e89b-12d3-a456-426614174001",
    )
    second_tunnel_result = _run_just(second_worktree, second_environment, "tunnel-setup")

    assert second_setup_result.returncode == 0, second_setup_result.stderr
    assert second_tunnel_result.returncode == 0, second_tunnel_result.stderr
    assert _snapshot_generated_worktree_state(primary_root) == primary_before_second
    assert _snapshot_generated_worktree_state(first_worktree) == first_before_second
    first_generated_state = _snapshot_generated_worktree_state(first_worktree)
    second_generated_state = _snapshot_generated_worktree_state(second_worktree)
    expected_second_hook_configuration = (
        "worktree",
        _worktree_configuration_origin(second_worktree),
        "core.hookspath",
        str(second_worktree / ".state" / "hooks"),
    )
    assert set(second_generated_state.git_configuration) - set(
        second_before_first.git_configuration
    ) == {expected_shared_configuration, expected_second_hook_configuration}
    assert first_generated_state.effective_hooks_path == str(first_worktree / ".state" / "hooks")
    assert second_generated_state.effective_hooks_path == str(second_worktree / ".state" / "hooks")
    assert (
        first_generated_state.effective_hooks_path != second_generated_state.effective_hooks_path
    )
    assert first_generated_state.source_status == ""
    assert second_generated_state.source_status == ""
    for worktree_root in (first_worktree, second_worktree):
        _assert_worktree_generated_paths_are_local(worktree_root)
    first_log = first_command_log.read_text(encoding="utf-8")
    second_log = second_command_log.read_text(encoding="utf-8")
    assert str(first_worktree) in first_log
    assert str(second_worktree) not in first_log
    assert str(second_worktree) in second_log
    assert str(first_worktree) not in second_log


def test_setup_reexecution_repairs_invalid_nginx_certificate_pair(tmp_path: Path) -> None:
    """Setup再実行が不正なNginx certificate pairを再生成するcontractを検証する.

    初回setup後にprivate keyを破損させ、2回目の`just setup`が同じworktree-local pathへvalid pairを
    再生成し、後続development preflightで読み込める状態へ収束することを確認する.

    Args:
        tmp_path (Path): 隔離Git repositoryとdeterministic certificate fixture用の
            temporary directory.

    Returns:
        None: Invalid certificate stateの検出、再生成、再検証を確認して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)

    first_result = _run_just(repository_root, environment, "setup")
    certificate_path = repository_root / ".state" / "certs" / "_wildcard.athena.localhost.pem"
    certificate_key_path = (
        repository_root / ".state" / "certs" / "_wildcard.athena.localhost-key.pem"
    )
    _ = certificate_key_path.write_text("corrupt private key\n", encoding="utf-8")

    second_result = _run_just(repository_root, environment, "setup")

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_path, certificate_key_path)
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("mkcert:-cert-file ") for line in command_log) == 2


def test_setup_reexecution_repairs_wrong_host_nginx_certificate(tmp_path: Path) -> None:
    """Setup再実行がrequired SANを持たないNginx certificateを再生成するcontractを検証する.

    初回setup後に別DNS名のdeterministic valid pairへ置換し、2回目の`just setup`が
    `*.athena.localhost` SANを持つpairへ収束させてvalidatorを通過することを確認する.

    Args:
        tmp_path (Path): 隔離Git repositoryとdeterministic certificate fixture用の
            temporary directory.

    Returns:
        None: Wrong-host certificateの検出、再生成、再検証を確認して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)

    first_result = _run_just(repository_root, environment, "setup")
    _ = _generate_nginx_certificate(
        repository_root,
        dns_name="wrong.example.test",
    )
    second_result = _run_just(repository_root, environment, "setup")
    validation_result = subprocess.run(
        [
            sys.executable,
            str(repository_root / "infra" / "development" / "validate_state.py"),
            "nginx-certificates",
            str(repository_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert validation_result.returncode == 0, validation_result.stderr
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("mkcert:-cert-file ") for line in command_log) == 2


def test_setup_reexecution_repairs_expired_nginx_certificate(tmp_path: Path) -> None:
    """Setup再実行が期限切れNginx certificateを再生成するcontractを検証する.

    初回setup後にkeyとSANを保ったcertificate validityを過去へ移し、2回目の`just setup`が
    現在有効なpairへ収束させてvalidatorを通過することを確認する.

    Args:
        tmp_path (Path): 隔離Git repositoryとexpired certificate用temporary directory.

    Returns:
        None: Expired certificateの検出、再生成、再検証を確認して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)

    first_result = _run_just(repository_root, environment, "setup")
    certificate_path = repository_root / ".state" / "certs" / "_wildcard.athena.localhost.pem"
    _replace_certificate_validity(
        certificate_path,
        not_before="200101000000Z",
        not_after="200102000000Z",
    )
    second_result = _run_just(repository_root, environment, "setup")
    validation_result = subprocess.run(
        [
            sys.executable,
            str(repository_root / "infra" / "development" / "validate_state.py"),
            "nginx-certificates",
            str(repository_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert validation_result.returncode == 0, validation_result.stderr
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("mkcert:-cert-file ") for line in command_log) == 2


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
    assert command_log == [
        "sysctl:-n net.ipv4.ip_unprivileged_port_start",
        "process-compose:up app worker nginx",
    ]


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
    (repository_root / ".state" / "nginx" / "nginx.conf").unlink()
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


def test_dev_rejects_stale_nginx_config_without_starting_processes(tmp_path: Path) -> None:
    """devがtracked templateと異なるgenerated Nginx configを拒否するcontractを検証する.

    Core stateのactual proxy configだけを古い内容へ変更し、`dev`がProcess Graphを開始せず
    current worktreeの`just setup`による再生成を案内することを確認する.

    Args:
        tmp_path (Path): Stale Nginx configを持つ隔離worktree用temporary directory.

    Returns:
        None: Config driftのpreflight failureとactionable recoveryを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    nginx_config_path = repository_root / ".state" / "nginx" / "nginx.conf"
    _ = nginx_config_path.write_text("stale generated config\n", encoding="utf-8")
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
    assert "Nginx config" in result.stderr
    assert "just setup" in result.stderr
    assert not command_log_path.exists()


def test_dev_rejects_invalid_nginx_certificate_without_starting_processes(
    tmp_path: Path,
) -> None:
    """devが読み込めないNginx certificate pairを拒否するcontractを検証する.

    Valid core stateのcertificateだけを破損させ、`dev`がProcess Graphを開始せずcurrent worktreeの
    `just setup`によるcertificate再生成を案内することを確認する.

    Args:
        tmp_path (Path): Invalid certificateを持つ隔離worktree用temporary directory.

    Returns:
        None: Certificate validation failureとactionable recoveryを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    certificate_path = repository_root / ".state" / "certs" / "_wildcard.athena.localhost.pem"
    _ = certificate_path.write_text("corrupt certificate\n", encoding="utf-8")
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
    assert "certificate" in result.stderr
    assert "just setup" in result.stderr
    assert not command_log_path.exists()


def test_dev_rejects_nginx_certificate_for_different_hostname(
    tmp_path: Path,
) -> None:
    """devが対象SANを持たないvalid certificate pairを起動前に拒否するcontractを検証する.

    鍵と一致して読み込める別DNS名のcertificateへ置換し、`dev`がProcess Graphを開始せず
    `just setup`による`*.athena.localhost` certificate再生成を案内することを確認する.

    Args:
        tmp_path (Path): Wrong-host certificateを持つ隔離worktree用temporary directory.

    Returns:
        None: Certificate SAN validation failureとProcess Compose未起動を検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    _ = _generate_nginx_certificate(repository_root, dns_name="wrong.example.test")
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
    assert "*.athena.localhost" in result.stderr
    assert "just setup" in result.stderr
    assert not command_log_path.exists()


@pytest.mark.parametrize(
    ("not_before", "not_after", "expected_diagnostic"),
    [
        pytest.param(
            "200101000000Z",
            "200102000000Z",
            "expired",
            id="expired",
        ),
        pytest.param(
            "490101000000Z",
            "491231235959Z",
            "not valid before",
            id="not-yet-valid",
        ),
    ],
)
def test_dev_rejects_nginx_certificate_outside_validity_window(
    tmp_path: Path,
    not_before: str,
    not_after: str,
    expected_diagnostic: str,
) -> None:
    """devが現在時刻を含まないNginx certificate validity windowを拒否するcontractを検証する.

    KeyとSANが正しいcertificateのnotBefore/notAfterだけを過去または未来へ移し、`dev`が
    Process Graphを開始せず期限状態を報告して`just setup`による再生成を案内することを確認する.

    Args:
        tmp_path (Path): 時間範囲外certificateを持つ隔離worktree用temporary directory.
        not_before (str): Fixture certificateへ設定するASN.1 UTCTime開始値.
        not_after (str): Fixture certificateへ設定するASN.1 UTCTime終了値.
        expected_diagnostic (str): Standard errorへ含めるvalidity failure識別子.

    Returns:
        None: Certificate validity validation failureとProcess Compose未起動を検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    certificate_path = repository_root / ".state" / "certs" / "_wildcard.athena.localhost.pem"
    _replace_certificate_validity(
        certificate_path,
        not_before=not_before,
        not_after=not_after,
    )
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
    assert expected_diagnostic in result.stderr
    assert "just setup" in result.stderr
    assert not command_log_path.exists()


def test_dev_reports_low_port_prerequisite_without_mutating_host(tmp_path: Path) -> None:
    """devが80/443 prerequisite不足をsetupへ戻しhost stateを変更しないcontractを検証する.

    Core file stateが揃っていてもLinuxのunprivileged port thresholdが80より大きい場合、
    `dev`はread-only checkだけを行い、sudo、sysctl mutation、Process Graph起動へ進まない.

    Args:
        tmp_path (Path): Fake kernel settingとProcess Graph adapterを置くtemporary directory.

    Returns:
        None: Low-port prerequisite failureがactionableかつ非破壊であることを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    _ = (repository_root / "sysctl-state").write_text("1024\n", encoding="utf-8")
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
    assert "net.ipv4.ip_unprivileged_port_start" in result.stderr
    assert "just setup" in result.stderr
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        "sysctl:-n net.ipv4.ip_unprivileged_port_start",
    ]


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
    _ = tunnel_config_path.write_text(
        "ingress:\n  - service: http_status:404\n",
        encoding="utf-8",
    )
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
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        "sysctl:-n net.ipv4.ip_unprivileged_port_start",
    ]


def test_dev_tunnel_requires_fixed_worktree_local_credentials_file(
    tmp_path: Path,
) -> None:
    """dev-tunnelが固定pathのtunnel execution credentialを要求するcontractを検証する.

    Core state、tunnel config、account origin certificateだけを用意し、execution credential不足時は
    Process Graphを開始せず`.state/cloudflared/credentials.json`の回復案内を返すことを確認する.

    Args:
        tmp_path (Path): Execution credential不足の隔離worktree用temporary directory.

    Returns:
        None: Fixed credential pathのpreflight failureを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    tunnel_state_path = repository_root / ".state" / "cloudflared"
    _ = (tunnel_state_path / "config.yml").write_text(
        "ingress:\n  - service: http_status:404\n",
        encoding="utf-8",
    )
    origin_certificate_path = tunnel_state_path / "login-home" / ".cloudflared" / "cert.pem"
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

    assert result.returncode != 0
    assert ".state/cloudflared/credentials.json" in result.stderr
    assert "tunnel-setup" in result.stderr
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        "sysctl:-n net.ipv4.ip_unprivileged_port_start",
    ]


def test_dev_tunnel_rejects_malformed_execution_credentials(tmp_path: Path) -> None:
    """dev-tunnelがparseできないexecution credential JSONを拒否するcontractを検証する.

    Fixed credential pathへ不正なJSONを置き、`dev-tunnel`がProcess Graphを開始せずCloudflared
    create schemaを満たすJSON objectへの置換を案内することを確認する.

    Args:
        tmp_path (Path): Malformed credentialを持つ隔離worktree用temporary directory.

    Returns:
        None: Credential content validation failureを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    tunnel_state_path = repository_root / ".state" / "cloudflared"
    _ = (tunnel_state_path / "config.yml").write_text(
        "ingress:\n  - service: http_status:404\n",
        encoding="utf-8",
    )
    origin_certificate_path = tunnel_state_path / "login-home" / ".cloudflared" / "cert.pem"
    _ = origin_certificate_path.parent.mkdir(parents=True)
    _ = origin_certificate_path.write_text("fixture account credential\n", encoding="utf-8")
    _ = (tunnel_state_path / "credentials.json").write_text(
        "not-json\n",
        encoding="utf-8",
    )
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
    assert "JSON object" in result.stderr
    assert ".state/cloudflared/credentials.json" in result.stderr
    assert not any(
        line.startswith("process-compose:")
        for line in command_log_path.read_text(encoding="utf-8").splitlines()
    )


@pytest.mark.parametrize(
    ("credentials", "expected_diagnostic"),
    [
        pytest.param(
            {
                "TunnelSecret": VALID_TUNNEL_SECRET,
                "TunnelID": VALID_TUNNEL_ID,
            },
            "AccountTag",
            id="missing-account-tag",
        ),
        pytest.param(
            {
                "AccountTag": "fixture-account",
                "TunnelID": VALID_TUNNEL_ID,
            },
            "TunnelSecret",
            id="missing-tunnel-secret",
        ),
        pytest.param(
            {
                "AccountTag": "fixture-account",
                "TunnelSecret": VALID_TUNNEL_SECRET,
            },
            "TunnelID",
            id="missing-tunnel-id",
        ),
        pytest.param(
            {**VALID_TUNNEL_CREDENTIALS, "AccountTag": 42},
            "AccountTag",
            id="non-string-account-tag",
        ),
        pytest.param(
            {**VALID_TUNNEL_CREDENTIALS, "AccountTag": ""},
            "AccountTag",
            id="empty-account-tag",
        ),
        pytest.param(
            {**VALID_TUNNEL_CREDENTIALS, "TunnelSecret": 42},
            "TunnelSecret",
            id="non-string-tunnel-secret",
        ),
        pytest.param(
            {**VALID_TUNNEL_CREDENTIALS, "TunnelSecret": "not-base64"},
            "Base64",
            id="invalid-base64-tunnel-secret",
        ),
        pytest.param(
            {
                **VALID_TUNNEL_CREDENTIALS,
                "TunnelSecret": base64.b64encode(bytes(31)).decode("ascii"),
            },
            "32 bytes",
            id="short-tunnel-secret",
        ),
        pytest.param(
            {**VALID_TUNNEL_CREDENTIALS, "TunnelID": 42},
            "TunnelID",
            id="non-string-tunnel-id",
        ),
        pytest.param(
            {**VALID_TUNNEL_CREDENTIALS, "TunnelID": "not-a-uuid"},
            "UUID",
            id="invalid-tunnel-id",
        ),
    ],
)
def test_dev_tunnel_rejects_invalid_execution_credential_fields(
    tmp_path: Path,
    credentials: dict[str, object],
    expected_diagnostic: str,
) -> None:
    """dev-tunnelが不正なcredential fieldを起動前に拒否するcontractを検証する.

    Cloudflaredが生成するcredential schemaのrequired field、string type、Base64 secret長、UUIDを
    1条件ずつ破り、`dev-tunnel`がProcess Graphを開始せず該当fieldを報告することを確認する.

    Args:
        tmp_path (Path): Invalid credentialを持つ隔離worktree用temporary directory.
        credentials (dict[str, object]): 1つのschema条件を破るcredential mapping.
        expected_diagnostic (str): Standard errorへ含めるfieldまたはencoding識別子.

    Returns:
        None: Credential schema validation failureとProcess Compose未起動を検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    tunnel_state_path = repository_root / ".state" / "cloudflared"
    _ = (tunnel_state_path / "config.yml").write_text(
        "ingress:\n  - service: http_status:404\n",
        encoding="utf-8",
    )
    origin_certificate_path = tunnel_state_path / "login-home" / ".cloudflared" / "cert.pem"
    _ = origin_certificate_path.parent.mkdir(parents=True)
    _ = origin_certificate_path.write_text("fixture account credential\n", encoding="utf-8")
    _ = (tunnel_state_path / "credentials.json").write_text(
        _serialize_tunnel_credentials(credentials),
        encoding="utf-8",
    )
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
    assert expected_diagnostic in result.stderr
    assert not any(
        line.startswith("process-compose:")
        for line in command_log_path.read_text(encoding="utf-8").splitlines()
    )


def test_dev_tunnel_rejects_invalid_cloudflared_ingress_config(tmp_path: Path) -> None:
    """dev-tunnelがCloudflared ingress validation failureを伝播するcontractを検証する.

    Fixed worktree-local tunnel stateを揃えた上でCloudflared validatorを失敗させ、Process Graphを
    開始せずvalidatorのexit statusとdiagnosticを保持することを確認する.

    Args:
        tmp_path (Path): Invalid ingress configを持つ隔離worktree用temporary directory.

    Returns:
        None: Cloudflared config validationのfail-fast behaviorを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    _initialize_git_repository(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    _create_complete_core_state(repository_root)
    tunnel_state_path = repository_root / ".state" / "cloudflared"
    tunnel_config_path = tunnel_state_path / "config.yml"
    _ = tunnel_config_path.write_text("invalid ingress config\n", encoding="utf-8")
    _ = (tunnel_state_path / "credentials.json").write_text(
        _serialize_tunnel_credentials(VALID_TUNNEL_CREDENTIALS),
        encoding="utf-8",
    )
    origin_certificate_path = tunnel_state_path / "login-home" / ".cloudflared" / "cert.pem"
    _ = origin_certificate_path.parent.mkdir(parents=True)
    _ = origin_certificate_path.write_text("fixture account credential\n", encoding="utf-8")
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "cloudflared",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'cloudflared:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        echo 'fixture ingress config is invalid' >&2
        exit 47
        """,
    )
    _write_executable(
        binary_directory / "process-compose",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'process-compose:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        """,
    )

    result = _run_just(repository_root, environment, "dev-tunnel")

    assert result.returncode == 47
    assert "ingress config is invalid" in result.stderr
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        "sysctl:-n net.ipv4.ip_unprivileged_port_start",
        f"cloudflared:tunnel --config {tunnel_config_path} ingress validate",
    ]


def test_dev_tunnel_reads_worktree_local_cloudflare_config(tmp_path: Path) -> None:
    """dev-tunnelが現在worktreeのgenerated tunnel stateだけを使うcontractを検証する.

    `.state/cloudflared`配下のconfig、origin certificate、execution credentialを配置し、旧root
    pathや別worktreeへfallbackせずvalidation後にcloudflared processを追加することを確認する.

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
    _ = tunnel_config_path.write_text(
        "ingress:\n  - service: http_status:404\n",
        encoding="utf-8",
    )
    origin_certificate_path = (
        tunnel_config_path.parent / "login-home" / ".cloudflared" / "cert.pem"
    )
    _ = origin_certificate_path.parent.mkdir(parents=True)
    _ = origin_certificate_path.write_text("fixture account credential\n", encoding="utf-8")
    _ = (tunnel_config_path.parent / "credentials.json").write_text(
        _serialize_tunnel_credentials(VALID_TUNNEL_CREDENTIALS),
        encoding="utf-8",
    )
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "cloudflared",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'cloudflared:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        """,
    )
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
    assert command_log == [
        "sysctl:-n net.ipv4.ip_unprivileged_port_start",
        f"cloudflared:tunnel --config {tunnel_config_path} ingress validate",
        "process-compose:up app worker nginx cloudflared",
    ]


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
    _ = tunnel_config_path.write_text(
        "ingress:\n  - service: http_status:404\n",
        encoding="utf-8",
    )
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
        echo 'fixture Cloudflared ingress validation failed' >&2
        exit 43
        """,
    )

    result = _run_just(repository_root, environment, "tunnel-setup")

    assert result.returncode == 43
    assert "ingress validation" in result.stderr
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    expected_validation_command = (
        f"cloudflared:tunnel --config {tunnel_config_path} ingress validate"
    )
    assert command_log == [expected_validation_command]
    assert not (repository_root / ".venv").exists()
    assert not (repository_root / ".state" / "postgres").exists()


def test_tunnel_setup_initializes_account_state_and_guides_execution_credential(
    tmp_path: Path,
) -> None:
    """tunnel-setupがaccount stateを初期化しfixed execution credentialを案内するcontractを検証する.

    Fake loginが`$HOME/.cloudflared/cert.pem`を生成した後、missing execution credentialにfixed
    create commandを返すことを確認する. Credential配置後の再実行はloginを繰り返さずconfig、
    account、credentialが利用可能な状態へ収束する.

    Args:
        tmp_path (Path): Tunnel-only stateとfake cloudflaredを置くtemporary directory.

    Returns:
        None: Account login、credential guidance、再実行の収束を検証して完了する.
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
    _ = tunnel_config_path.write_text(
        "ingress:\n  - service: http_status:404\n",
        encoding="utf-8",
    )
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
        expected_ingress="tunnel --config $PWD/.state/cloudflared/config.yml ingress validate"
        if [[ "$*" == "$expected_ingress" ]]; then
          exit 0
        fi
        expected_validation="tunnel --origincert $ATHENA_TEST_ORIGIN_CERTIFICATE"
        expected_validation+=" --config $PWD/.state/cloudflared/config.yml list"
        [[ "$*" == "$expected_validation" && -f "$ATHENA_TEST_ORIGIN_CERTIFICATE" ]]
        """,
    )

    first_result = _run_just(repository_root, environment, "tunnel-setup")
    credentials_path = tunnel_state_path / "credentials.json"
    _ = credentials_path.write_text(
        _serialize_tunnel_credentials(VALID_TUNNEL_CREDENTIALS),
        encoding="utf-8",
    )
    second_result = _run_just(repository_root, environment, "tunnel-setup")

    assert first_result.returncode != 0
    assert str(credentials_path) in first_result.stderr
    assert "create --credentials-file" in first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert origin_certificate_path.is_file()
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    expected_ingress_command = f"cloudflared:tunnel --config {tunnel_config_path} ingress validate"
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
        expected_ingress_command,
        expected_ingress_command,
        expected_validation_command,
    ]
    assert not (repository_root / ".venv").exists()
    assert not (repository_root / ".state" / "postgres").exists()


def test_validation_recipes_use_root_owned_library_and_propagate_exit_status(
    tmp_path: Path,
) -> None:
    """Validation recipeがroot-owned実装へ委譲してfailureを保持する契約を検証する.

    Public Just interfaceからquality、docstring、test、fix、Python inventoryを実行し、legacy
    scriptを経由せず内部libraryの対応functionへ到達して各exit statusをそのまま返すことを確認する.

    Args:
        tmp_path (Path): Isolated justfileとfake validation libraryを置くtemporary directory.

    Returns:
        None: Public validation recipeの委譲先とfailure propagationを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    validation_library_path = (
        repository_root / "tools" / "monorepo_migration" / "repository_validation.sh"
    )
    validation_library_path.parent.mkdir(parents=True, exist_ok=True)
    _write_executable(
        validation_library_path,
        """
        #!/usr/bin/env bash
        set -euo pipefail
        _record_validation_call() {
          printf '%s\n' "$1" >> "$ATHENA_TEST_COMMAND_LOG"
          return "$2"
        }
        run_quality() { _record_validation_call quality 21; }
        run_docstrings() { _record_validation_call docstrings 22; }
        run_test() { _record_validation_call test 23; }
        run_fix() { _record_validation_call fix 24; }
        run_python_files() { _record_validation_call python-files 25; }
        """,
    )

    expected_exit_statuses = {
        "quality": 21,
        "docstrings": 22,
        "test": 23,
        "fix": 24,
        "python-files": 25,
    }
    results = {
        recipe: _run_just(repository_root, environment, recipe)
        for recipe in expected_exit_statuses
    }
    ci_result = _run_just(repository_root, environment, "ci")
    all_result = _run_just(repository_root, environment, "all")

    assert {
        recipe: result.returncode for recipe, result in results.items()
    } == expected_exit_statuses
    assert ci_result.returncode == expected_exit_statuses["quality"]
    assert all_result.returncode == expected_exit_statuses["quality"]
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        *expected_exit_statuses,
        "quality",
        "quality",
    ]


@pytest.mark.parametrize(
    "pytest_exit_status",
    [
        pytest.param(1, id="test-failure"),
        pytest.param(5, id="zero-selection"),
    ],
)
def test_process_lifecycle_check_selects_infrastructure_and_propagates_pytest_status(
    tmp_path: Path,
    pytest_exit_status: int,
) -> None:
    """Process lifecycle checkpointがinfra markerとpytest exit statusを保持する契約を検証する.

    Args:
        tmp_path (Path): Isolated justfileとfake uv commandを置くtemporary directory.
        pytest_exit_status (int): Test failureまたはzero-selectionを表すfake pytest status.

    Returns:
        None: Opt-in environment、infra selection、failure propagationを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    environment["ATHENA_TEST_PYTEST_EXIT_STATUS"] = str(pytest_exit_status)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "uname",
        """
        #!/usr/bin/env bash
        printf 'Linux\n'
        """,
    )
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'uv:%s|ATHENA_RUN_PROCESS_LIFECYCLE_CHECK=%s\n' \
          "$*" "${ATHENA_RUN_PROCESS_LIFECYCLE_CHECK:-<unset>}" \
          >> "$ATHENA_TEST_COMMAND_LOG"
        exit "$ATHENA_TEST_PYTEST_EXIT_STATUS"
        """,
    )

    result = _run_just(repository_root, environment, "process-lifecycle-check")

    expected_test_path = (
        repository_root
        / "tools"
        / "monorepo_migration"
        / "tests"
        / "test_development_infrastructure.py"
    )
    expected_command = (
        "uv:run pytest -p no:cacheprovider -m development_infrastructure "
        f"{expected_test_path} -q -vv -s"
    )
    assert result.returncode == pytest_exit_status, result.stderr
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        f"{expected_command}|ATHENA_RUN_PROCESS_LIFECYCLE_CHECK=1"
    ]


def test_process_lifecycle_check_rejects_non_linux_before_pytest(tmp_path: Path) -> None:
    """Dedicated development checkpointがnon-Linuxでfalse successを返さないことを検証する.

    Args:
        tmp_path (Path): Fake `uname`とuv invocation logを置くtemporary directory.

    Returns:
        None: Actionable non-zero diagnosticとuv未実行を確認して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "uname",
        """
        #!/usr/bin/env bash
        printf 'Darwin\n'
        """,
    )
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        printf 'uv:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        exit 0
        """,
    )

    result = _run_just(repository_root, environment, "process-lifecycle-check")

    assert result.returncode != 0
    assert "requires a Linux Nix development shell" in result.stderr
    assert not command_log_path.exists()


def test_database_and_worktree_recipes_preserve_specialized_helper_contracts(
    tmp_path: Path,
) -> None:
    """Database operationとworktree lifecycleの既存導線をroot recipeから検証する.

    Alembicはserver workspaceから実行し、test database operationはroot-owned環境解決からAthena
    CLIへ、worktree lifecycleはspecialized helperへargumentとexit statusを変えずに委譲する.

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
    _ = environment.pop("ATHENA_TEST_DATABASE_URL", None)
    _ = environment.pop("ATHENA_TEST_VALKEY_URL", None)
    _ = environment.pop("DATABASE_URL", None)
    _ = environment.pop("VALKEY_URL", None)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        if [[ "$*" == "run --directory"* ]]; then
          printf 'uv:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        else
          printf 'uv:%s|ENVIRONMENT=%s|DATABASE_URL=%s|VALKEY_URL=%s\n' \
            "$*" "${ENVIRONMENT:-<unset>}" "${DATABASE_URL:-<unset>}" \
            "${VALKEY_URL:-<unset>}" >> "$ATHENA_TEST_COMMAND_LOG"
        fi
        exit 31
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
    assert all(result.returncode == 31 for result in database_results.values())
    assert worktree_result.returncode == 29
    command_log = command_log_path.read_text(encoding="utf-8").splitlines()
    default_database_url = "postgresql://localhost:5432/athena_test"
    default_valkey_url = "redis://localhost:6379/1"
    default_environment_summary = (
        "ENVIRONMENT=test|DATABASE_URL="
        + default_database_url
        + "|VALKEY_URL="
        + default_valkey_url
    )
    assert command_log == [
        f"uv:run --directory {repository_root}/apps/athena_server alembic upgrade head",
        f"uv:run athena db create --env test|{default_environment_summary}",
        f"uv:run athena db migrate --env test|{default_environment_summary}",
        f"uv:run athena test --env test|{default_environment_summary}",
        "agent-worktree:fixture-task --agent codex",
    ]


def test_migration_check_applies_head_before_current_revision_verification(
    tmp_path: Path,
) -> None:
    """Migration checkがhead適用後にrecorded currentとの一致を検証する契約を検証する.

    Args:
        tmp_path (Path): Isolated task gatewayとfake uv commandを置くtemporary directory.

    Returns:
        None: Migrationとcurrent/head verifierの順序またはargumentが異なる場合に失敗する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    environment, command_log_path = _fake_setup_environment(repository_root)
    binary_directory = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'uv:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        """,
    )

    result = _run_just(repository_root, environment, "migration-check")

    assert result.returncode == 0, result.stderr
    expected_current_check = " ".join(
        (
            "uv:run python",
            f"{repository_root}/tools/monorepo_migration/verify_preflight_baseline.py",
            "--baseline",
            f"{repository_root}/.kiro/specs/monorepo-migration/preflight-baseline.json",
            "--mode post-cutover --alembic-current",
        )
    )
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        f"uv:run --directory {repository_root}/apps/athena_server alembic upgrade head",
        expected_current_check,
    ]


def test_database_recipes_prefer_explicit_overrides_and_server_environment_file(
    tmp_path: Path,
) -> None:
    """Test database recipeがexplicit overrideとserver env fileを優先する契約を検証する.

    Explicit `ATHENA_TEST_*` valueを親process値より優先し、server-owned `.env.test`が存在する
    場合は親processの`DATABASE_URL`と`VALKEY_URL`をCLIへ渡さないことを確認する.

    Args:
        tmp_path (Path): Isolated task gatewayとfake uv commandを置くtemporary directory.

    Returns:
        None: Test environment resolutionのobservable subprocess inputを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _copy_root_task_gateway(repository_root)
    base_environment, command_log_path = _fake_setup_environment(repository_root)
    binary_directory = Path(base_environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    _write_executable(
        binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'uv:%s|DATABASE_URL=%s|VALKEY_URL=%s\n' \
          "$*" "${DATABASE_URL:-<unset>}" "${VALKEY_URL:-<unset>}" \
          >> "$ATHENA_TEST_COMMAND_LOG"
        """,
    )

    override_database_url = "postgresql://override/athena_test"
    override_valkey_url = "redis://override/9"
    override_environment = base_environment.copy()
    override_environment.update(
        {
            "ATHENA_TEST_DATABASE_URL": override_database_url,
            "ATHENA_TEST_VALKEY_URL": override_valkey_url,
            "DATABASE_URL": "postgresql://parent/ignored",
            "VALKEY_URL": "redis://parent/8",
        }
    )
    override_result = _run_just(
        repository_root,
        override_environment,
        "db-test-run",
    )

    server_environment_file = repository_root / "apps" / "athena_server" / ".env.test"
    server_environment_file.parent.mkdir(parents=True)
    _ = server_environment_file.write_text("fixture=true\n", encoding="utf-8")
    server_file_environment = base_environment.copy()
    _ = server_file_environment.pop("ATHENA_TEST_DATABASE_URL", None)
    _ = server_file_environment.pop("ATHENA_TEST_VALKEY_URL", None)
    server_file_environment.update(
        {
            "DATABASE_URL": "postgresql://parent/must-not-leak",
            "VALKEY_URL": "redis://parent/7",
        }
    )
    server_file_result = _run_just(
        repository_root,
        server_file_environment,
        "db-test-run",
    )

    assert override_result.returncode == 0, override_result.stderr
    assert server_file_result.returncode == 0, server_file_result.stderr
    override_environment_summary = (
        "DATABASE_URL=" + override_database_url + "|VALKEY_URL=" + override_valkey_url
    )
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        f"uv:run athena test --env test|{override_environment_summary}",
        "uv:run athena test --env test|DATABASE_URL=<unset>|VALKEY_URL=<unset>",
    ]


def test_legacy_database_entrypoint_delegates_to_root_task_interface(tmp_path: Path) -> None:
    """Task 4.6前のdatabase helperがcanonical Just recipeだけを呼ぶ契約を検証する.

    Legacy subcommandを実行し、root justfileと対応recipeへargumentを写像してdelegateのexit statusを
    そのまま返すことを確認する. 旧helper内でAthena CLIを直接再実装しない.

    Args:
        tmp_path (Path): Legacy entrypoint、fake Just、command logを置くtemporary directory.

    Returns:
        None: Legacy database入口のmappingとfailure propagationを検証して完了する.
    """
    repository_root = tmp_path / "repository"
    scripts_directory = repository_root / "scripts"
    scripts_directory.mkdir(parents=True)
    _ = shutil.copy2(LEGACY_DEV_TASKS_PATH, scripts_directory / "dev-tasks.sh")
    fake_binary_directory = repository_root / "fake-bin"
    fake_binary_directory.mkdir()
    command_log_path = repository_root / "commands.log"
    _write_executable(
        fake_binary_directory / "just",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'just:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        exit 27
        """,
    )
    _write_executable(
        fake_binary_directory / "uv",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        printf 'uv:%s\n' "$*" >> "$ATHENA_TEST_COMMAND_LOG"
        exit 26
        """,
    )
    environment = os.environ.copy()
    environment["ATHENA_TEST_COMMAND_LOG"] = str(command_log_path)
    environment["PATH"] = f"{fake_binary_directory}{os.pathsep}{environment['PATH']}"

    command_to_recipe = {
        "db:test:create": "db-test-create",
        "db:test:migrate": "db-test-migrate",
        "db:test:run": "db-test-run",
    }
    results = {
        command: subprocess.run(
            [str(scripts_directory / "dev-tasks.sh"), command],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
        )
        for command in command_to_recipe
    }

    assert all(result.returncode == 27 for result in results.values())
    assert command_log_path.read_text(encoding="utf-8").splitlines() == [
        f"just:--justfile {repository_root}/justfile {recipe}"
        for recipe in command_to_recipe.values()
    ]


def test_public_recipe_catalog_exposes_root_workflows(tmp_path: Path) -> None:
    """Root task catalogがpublic workflowとdevelopment checkpointを公開する契約を検証する.

    Args:
        tmp_path (Path): Public justfileを置くisolated repository directory.

    Returns:
        None: Development、validation、checkpoint、database、audit recipeを検証して完了する.
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
        "fix",
        "python-files",
        "build",
        "db-migrate",
        "db-test-create",
        "db-test-migrate",
        "db-test-run",
        "migration-check",
        "process-lifecycle-check",
        "ci",
        "all",
        "audit-monorepo",
        "worktree",
    ):
        assert f"    {recipe_name}" in result.stdout
