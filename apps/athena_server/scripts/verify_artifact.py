"""Athena server wheelをsource fallbackのないconsumer環境で検証するentrypoint."""

from __future__ import annotations

import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SERVER_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVER_WORKSPACE_ROOT.parents[1]
CRYPTO_WORKSPACE_ROOT = REPOSITORY_ROOT / "packages" / "athena_crypto"
SERVER_WHEEL_PATTERN = "athena-*.whl"
CRYPTO_WHEEL_PATTERN = "athena_crypto-*.whl"
SERVER_NAMESPACE_MEMBERS = {
    "osu_server/__init__.py",
    "osu_server/__main__.py",
    "osu_server/worker.py",
    "athena_cli/__init__.py",
    "athena_cli/main.py",
}


def _clean_environment() -> dict[str, str]:
    """Source checkoutをPython importへ注入する設定を除いたenvironmentを返す.

    Returns:
        dict[str, str]: consumer subprocessへ渡すsanitized environment mapping.
    """
    environment = os.environ.copy()
    for variable_name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "UV_PROJECT",
        "UV_PROJECT_ENVIRONMENT",
        "UV_WORKING_DIR",
    ):
        _ = environment.pop(variable_name, None)
    return environment


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    """成功が必須のexternal commandをshellを介さず実行する.

    Args:
        command (Sequence[str]): 実行するcommandと引数.
        cwd (Path): commandのworking directory.
        environment (Mapping[str, str]): child processへ渡すenvironment mapping.

    Returns:
        subprocess.CompletedProcess[str]: 成功したcommandのcaptured outputを含む結果.

    Raises:
        RuntimeError: commandがnon-zero exit statusで終了した場合.
    """
    completed_process = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if completed_process.returncode != 0:
        raise _command_failure(command, completed_process)
    return completed_process


def _command_failure(
    command: Sequence[str],
    completed_process: subprocess.CompletedProcess[str],
) -> RuntimeError:
    """External commandの失敗情報を保持するRuntimeErrorを組み立てる.

    Args:
        command (Sequence[str]): 実行したcommandと引数.
        completed_process (subprocess.CompletedProcess[str]): exit statusとcaptured output.

    Returns:
        RuntimeError: callerが送出する詳細なcommand failure.
    """
    command_text = " ".join(command)
    message = (
        f"Command failed ({completed_process.returncode}): {command_text}\n"
        f"stdout:\n{completed_process.stdout}\n"
        f"stderr:\n{completed_process.stderr}"
    )
    return RuntimeError(message)


def _single_wheel(wheels_directory: Path, pattern: str, distribution_name: str) -> Path:
    """Build directoryから指定distributionの唯一のwheelを返す.

    Args:
        wheels_directory (Path): clean build artifactを置いたdirectory.
        pattern (str): distribution wheelだけに一致するglob pattern.
        distribution_name (str): failure messageへ表示するdistribution名.

    Returns:
        Path: archive検査とconsumer installに使う単一wheel.

    Raises:
        RuntimeError: 一致するwheelが0個または複数個の場合.
    """
    wheels = sorted(wheels_directory.glob(pattern))
    if len(wheels) != 1:
        message = f"Expected exactly one {distribution_name} wheel, got {wheels!r}"
        raise RuntimeError(message)
    return wheels[0]


def _verify_server_wheel_archive(wheel_path: Path) -> None:
    """Server wheelが両namespaceとAthena console entrypointを含むことを検証する.

    Args:
        wheel_path (Path): clean Hatchling buildで作成したserver wheel.

    Returns:
        None: archive memberとentrypoint metadataを検証して完了する.

    Raises:
        RuntimeError: 必須sourceまたはconsole entrypoint metadataが欠落する場合.
    """
    with zipfile.ZipFile(wheel_path) as wheel_archive:
        member_names = set(wheel_archive.namelist())
        entrypoint_members = sorted(
            member_name
            for member_name in member_names
            if member_name.endswith(".dist-info/entry_points.txt")
        )
        if len(entrypoint_members) != 1:
            message = f"Expected one entry_points.txt member, got {entrypoint_members!r}"
            raise RuntimeError(message)
        entrypoint_source = wheel_archive.read(entrypoint_members[0]).decode("utf-8")

    missing_members = sorted(SERVER_NAMESPACE_MEMBERS.difference(member_names))
    if missing_members:
        message = f"Server wheel is missing namespace members: {missing_members!r}"
        raise RuntimeError(message)
    if "athena = athena_cli.main:main" not in entrypoint_source:
        message = "Server wheel does not expose athena = athena_cli.main:main"
        raise RuntimeError(message)


def _venv_python(venv_root: Path) -> Path:
    """Current platformのconsumer virtual environment Pythonを返す.

    Args:
        venv_root (Path): `venv` moduleが作成したconsumer environment root.

    Returns:
        Path: wheel installとsmoke testへ使うPython executable.

    Raises:
        RuntimeError: Python executableが作成されなかった場合.
    """
    executable_name = "python.exe" if os.name == "nt" else "python"
    executable_directory = "Scripts" if os.name == "nt" else "bin"
    python_path = venv_root / executable_directory / executable_name
    if not python_path.is_file():
        message = f"Consumer venv Python executable is missing: {python_path}"
        raise RuntimeError(message)
    return python_path


def _create_locked_consumer_environment(
    consumer_venv: Path,
    environment: Mapping[str, str],
) -> None:
    """Root lockからworkspace sourceを含まないconsumer dependency environmentを作成する.

    Args:
        consumer_venv (Path): uvが作成するisolated consumer virtual environmentのroot.
        environment (Mapping[str, str]): source import設定を除去したbase environment.

    Returns:
        None: lock済みruntime dependencyだけをconsumer environmentへ同期して完了する.
    """
    consumer_environment = dict(environment)
    consumer_environment["UV_PROJECT_ENVIRONMENT"] = str(consumer_venv)
    _ = _run_command(
        [
            "uv",
            "sync",
            "--locked",
            "--package",
            "athena",
            "--no-dev",
            "--no-install-project",
            "--no-install-workspace",
            "--offline",
        ],
        cwd=REPOSITORY_ROOT,
        environment=consumer_environment,
    )


def _install_consumer_wheels(
    consumer_python: Path,
    crypto_wheel: Path,
    server_wheel: Path,
    consumer_root: Path,
    environment: Mapping[str, str],
) -> None:
    """Fresh product wheelsをlocked consumerへinstallしdependency closureを検証する.

    Args:
        consumer_python (Path): lock済みdependency environmentのPython executable.
        crypto_wheel (Path): clean buildしたathena-crypto wheel.
        server_wheel (Path): clean buildしたAthena server wheel.
        consumer_root (Path): source checkout外にあるconsumer working directory.
        environment (Mapping[str, str]): sanitized child environment mapping.

    Returns:
        None: wheelsをdependency解決なしでinstallし、installed dependency closureを検証して
            完了する.
    """
    _ = _run_command(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(consumer_python),
            "--offline",
            "--no-index",
            "--no-deps",
            "--strict",
            str(crypto_wheel),
            str(server_wheel),
        ],
        cwd=consumer_root,
        environment=environment,
    )
    _ = _run_command(
        ["uv", "pip", "check", "--python", str(consumer_python)],
        cwd=consumer_root,
        environment=environment,
    )


def _runtime_environment(
    base_environment: Mapping[str, str],
    temporary_root: Path,
) -> dict[str, str]:
    """Installed app、worker、CLI smokeへ必要なtest-only environmentを返す.

    Args:
        base_environment (Mapping[str, str]): source import設定を除去したenvironment mapping.
        temporary_root (Path): blob/logなどのruntime pathを閉じ込める一時directory.

    Returns:
        dict[str, str]: external serviceへ接続せずmodule importを完了できる設定.
    """
    environment = dict(base_environment)
    environment.update(
        {
            "ENVIRONMENT": "test",
            "DATABASE_URL": "postgresql+asyncpg://athena:athena@127.0.0.1:5432/athena_test",
            "VALKEY_URL": "redis://127.0.0.1:6379/1",
            "BLOB_STORAGE_LOCAL_ROOT": str(temporary_root / "blobs"),
            "LOG_DIR": str(temporary_root / "logs"),
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return environment


def _verify_installed_namespaces(
    consumer_python: Path,
    consumer_venv: Path,
    consumer_root: Path,
    environment: Mapping[str, str],
) -> None:
    """Public namespaceがconsumer wheelから解決されsource treeへfallbackしないことを検証する.

    Args:
        consumer_python (Path): wheelsをinstallしたconsumer Python executable.
        consumer_venv (Path): module originが属するべきconsumer environment root.
        consumer_root (Path): source checkout外のconsumer working directory.
        environment (Mapping[str, str]): installed importへ必要なruntime environment.

    Returns:
        None: namespace originとsys.path isolationを検証して完了する.
    """
    probe_source = """
import sys
from pathlib import Path

import athena_cli
import athena_crypto
import osu_server

consumer_venv = Path(sys.argv[1]).resolve()
repository_root = Path(sys.argv[2]).resolve()
if not sys.flags.isolated:
    raise SystemExit("consumer namespace import did not run in isolated mode")
for module in (osu_server, athena_cli, athena_crypto):
    module_file = Path(module.__file__).resolve()
    if not module_file.is_relative_to(consumer_venv):
        raise SystemExit(f"module did not resolve from installed wheel: {module_file}")
forbidden_source_roots = (
    repository_root / "src",
    repository_root / "apps" / "athena_server" / "src",
    repository_root / "packages" / "athena_crypto" / "typings",
)
for entry in sys.path:
    resolved_entry = Path(entry or Path.cwd()).resolve()
    for source_root in forbidden_source_roots:
        if resolved_entry == source_root or resolved_entry.is_relative_to(source_root):
            raise SystemExit(f"source checkout leaked into consumer sys.path: {resolved_entry}")
"""
    _ = _run_command(
        [
            str(consumer_python),
            "-I",
            "-c",
            probe_source,
            str(consumer_venv),
            str(REPOSITORY_ROOT),
        ],
        cwd=consumer_root,
        environment=environment,
    )


def _verify_installed_app_import(
    consumer_python: Path,
    consumer_venv: Path,
    consumer_root: Path,
    environment: Mapping[str, str],
) -> None:
    """Installed app import targetがconsumer wheelからStarlette appを解決することを検証する.

    Args:
        consumer_python (Path): server wheelをinstallしたconsumer Python executable.
        consumer_venv (Path): app module originが属するべきconsumer environment root.
        consumer_root (Path): source checkout外のconsumer working directory.
        environment (Mapping[str, str]): app configをenvironment-onlyで構築する設定.

    Returns:
        None: direct import targetのobject typeとmodule originを検証して完了する.

    Raises:
        RuntimeError: app targetがStarlette appを返さないかwheel外のmoduleを解決する場合.
    """
    probe_source = """
import importlib
import sys
from pathlib import Path

from starlette.applications import Starlette
from uvicorn.importer import import_from_string

consumer_venv = Path(sys.argv[1]).resolve()
if not sys.flags.isolated:
    raise SystemExit("consumer app import did not run in isolated mode")
app = import_from_string("osu_server.app:app")
if not isinstance(app, Starlette):
    raise SystemExit(f"app target did not resolve to Starlette: {type(app)!r}")
app_module = importlib.import_module("osu_server.app")
app_module_path = Path(app_module.__file__).resolve()
if not app_module_path.is_relative_to(consumer_venv):
    raise SystemExit(f"app target resolved outside consumer wheel: {app_module_path}")
"""
    _ = _run_command(
        [str(consumer_python), "-I", "-c", probe_source, str(consumer_venv)],
        cwd=consumer_root,
        environment=environment,
    )


def _verify_installed_app_entrypoint(
    consumer_python: Path,
    consumer_root: Path,
    environment: Mapping[str, str],
) -> None:
    """Installed `python -m osu_server`がexpected Uvicorn targetを起動することを検証する.

    Args:
        consumer_python (Path): server wheelをinstallしたconsumer Python executable.
        consumer_root (Path): source checkout外のconsumer working directory.
        environment (Mapping[str, str]): app configをenvironment-onlyで構築する設定.

    Returns:
        None: exact module invocationとUvicorn引数を検証して完了する.

    Raises:
        RuntimeError: app entrypointがbaseline targetと異なる場合.
    """
    probe_source = """
import runpy

import uvicorn

calls: list[tuple[object, dict[str, object]]] = []

def record_uvicorn_call(app: object, **kwargs: object) -> None:
    calls.append((app, kwargs))

uvicorn.run = record_uvicorn_call
runpy.run_module("osu_server", run_name="__main__")
expected_call = (
    "osu_server.app:app",
    {
        "access_log": False,
        "host": "0.0.0.0",
        "port": 8000,
        "reload": False,
        "reload_dirs": None,
    },
)
if calls != [expected_call]:
    raise SystemExit(f"installed app entrypoint changed its Uvicorn contract: {calls!r}")
"""
    _ = _run_command(
        [str(consumer_python), "-I", "-c", probe_source],
        cwd=consumer_root,
        environment=environment,
    )


def _verify_installed_worker_broker(
    consumer_python: Path,
    consumer_root: Path,
    environment: Mapping[str, str],
) -> None:
    """Installed `osu_server.worker:broker` targetをimportできることを検証する.

    Args:
        consumer_python (Path): server wheelをinstallしたconsumer Python executable.
        consumer_root (Path): source checkout外のconsumer working directory.
        environment (Mapping[str, str]): worker module importへ必要なruntime environment.

    Returns:
        None: broker objectをinstalled namespaceから解決して完了する.
    """
    probe_source = "from osu_server.worker import broker; assert broker is not None"
    _ = _run_command(
        [str(consumer_python), "-I", "-c", probe_source],
        cwd=consumer_root,
        environment=environment,
    )


def _verify_installed_console_entrypoint(
    consumer_python: Path,
    consumer_venv: Path,
    consumer_root: Path,
    environment: Mapping[str, str],
) -> None:
    """Installed `athena` commandが既存command familyを公開することを検証する.

    Args:
        consumer_python (Path): console scriptをisolated modeで実行するconsumer Python executable.
        consumer_venv (Path): console scriptが作成されたconsumer environment root.
        consumer_root (Path): source checkout外のconsumer working directory.
        environment (Mapping[str, str]): CLI importへ必要なruntime environment.

    Returns:
        None: console scriptのsuccessとcommand catalogを検証して完了する.

    Raises:
        RuntimeError: console scriptが存在しないか既存command familyを表示しない場合.
    """
    executable_name = "athena.exe" if os.name == "nt" else "athena"
    executable_directory = "Scripts" if os.name == "nt" else "bin"
    console_script = consumer_venv / executable_directory / executable_name
    if not console_script.is_file():
        message = f"Installed athena console script is missing: {console_script}"
        raise RuntimeError(message)
    completed_process = _run_command(
        [str(consumer_python), "-I", str(console_script), "--help"],
        cwd=consumer_root,
        environment=environment,
    )
    missing_commands = sorted(
        command_name
        for command_name in ("config", "db", "dev", "env", "pp", "test")
        if command_name not in completed_process.stdout
    )
    if missing_commands:
        message = f"Installed athena help is missing commands: {missing_commands!r}"
        raise RuntimeError(message)


def main() -> None:
    """Clean server wheelをbuildしinstalled public entrypointを順に検証する.

    Returns:
        None: archiveと全installed smokeが成功した場合にoutcomeを標準出力へ報告する.
    """
    environment = _clean_environment()
    with tempfile.TemporaryDirectory(prefix="athena-server-artifact-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        wheels_directory = temporary_root / "wheels"
        cargo_target = temporary_root / "cargo-target"
        consumer_venv = temporary_root / "consumer-venv"
        consumer_root = temporary_root / "consumer"
        consumer_root.mkdir()

        _ = _run_command(
            [
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(wheels_directory),
                str(SERVER_WORKSPACE_ROOT),
            ],
            cwd=REPOSITORY_ROOT,
            environment=environment,
        )
        server_wheel = _single_wheel(wheels_directory, SERVER_WHEEL_PATTERN, "athena")
        _verify_server_wheel_archive(server_wheel)
        print("server wheel archive verified")

        crypto_build_environment = dict(environment)
        crypto_build_environment["CARGO_TARGET_DIR"] = str(cargo_target)
        _ = _run_command(
            [
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(wheels_directory),
                str(CRYPTO_WORKSPACE_ROOT),
            ],
            cwd=REPOSITORY_ROOT,
            environment=crypto_build_environment,
        )
        crypto_wheel = _single_wheel(
            wheels_directory,
            CRYPTO_WHEEL_PATTERN,
            "athena-crypto",
        )

        _create_locked_consumer_environment(consumer_venv, environment)
        consumer_python = _venv_python(consumer_venv)
        print("locked isolated consumer dependencies verified")
        _install_consumer_wheels(
            consumer_python,
            crypto_wheel,
            server_wheel,
            consumer_root,
            environment,
        )
        print("installed dependency closure verified")
        runtime_environment = _runtime_environment(environment, temporary_root)

        _verify_installed_namespaces(
            consumer_python,
            consumer_venv,
            consumer_root,
            runtime_environment,
        )
        print("installed namespaces verified")
        _verify_installed_app_import(
            consumer_python,
            consumer_venv,
            consumer_root,
            runtime_environment,
        )
        print("isolated direct app import verified")
        _verify_installed_app_entrypoint(
            consumer_python,
            consumer_root,
            runtime_environment,
        )
        print("installed app entrypoint verified")
        _verify_installed_worker_broker(
            consumer_python,
            consumer_root,
            runtime_environment,
        )
        print("installed worker broker verified")
        _verify_installed_console_entrypoint(
            consumer_python,
            consumer_venv,
            consumer_root,
            runtime_environment,
        )
        print("installed athena console entrypoint verified")

    print("athena server wheel artifact verification passed")


if __name__ == "__main__":
    main()
