"""athena_crypto wheelをclean consumer環境で検証するowner-owned entrypoint."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WHEEL_PACKAGE_SOURCE_PATH = "athena_crypto/__init__.py"
WHEEL_STUB_PATH = "athena_crypto/__init__.pyi"
WHEEL_NATIVE_STUB_PATH = "athena_crypto/athena_crypto.pyi"
WHEEL_TYPED_MARKER_PATH = "athena_crypto/py.typed"


def _clean_environment() -> dict[str, str]:
    """Source checkoutのPython import設定を除いたsubprocess environmentを返す.

    Returns:
        dict[str, str]: source treeをconsumer interpreterへ注入しないenvironment mapping.
    """
    environment = os.environ.copy()
    for variable_name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        _ = environment.pop(variable_name, None)
    return environment


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    """成功が必須のexternal commandを実行する.

    Args:
        command (Sequence[str]): shellを介さず実行するcommandと引数.
        cwd (Path): commandを実行するworking directory.
        environment (Mapping[str, str]): child processだけへ渡すenvironment mapping.
        allow_failure (bool): non-zero exit statusのresultをcallerへ返すか.

    Returns:
        subprocess.CompletedProcess[str]: 成功終了したcommandの標準出力と標準errorを含む結果.

    Raises:
        RuntimeError: commandがnon-zero exit statusで終了し、allow_failureがFalseの場合.
    """
    completed_process = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if completed_process.returncode != 0 and not allow_failure:
        raise _command_failure(command, completed_process)
    return completed_process


def _command_failure(
    command: Sequence[str],
    completed_process: subprocess.CompletedProcess[str],
) -> RuntimeError:
    """External commandの失敗内容を含むRuntimeErrorを組み立てる.

    Args:
        command (Sequence[str]): 実行したcommandと引数.
        completed_process (subprocess.CompletedProcess[str]): commandのexit statusとcaptured
            output.

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


def _single_wheel(wheels_directory: Path) -> Path:
    """Build出力directoryから唯一のathena_crypto wheelを取得する.

    Args:
        wheels_directory (Path): clean buildがwheelを書き出したdirectory.

    Returns:
        Path: artifact検証とconsumer installに使う単一wheel file.

    Raises:
        RuntimeError: athena_crypto wheelが0個または複数個生成された場合.
    """
    wheels = sorted(wheels_directory.glob("athena_crypto-*.whl"))
    if len(wheels) != 1:
        message = f"Expected exactly one athena_crypto wheel, got {wheels!r}"
        raise RuntimeError(message)
    return wheels[0]


def _verify_wheel_archive(wheel_path: Path) -> None:
    """Wheelが必要なnative/typing memberだけをpackage namespaceに含むことを検証する.

    Args:
        wheel_path (Path): clean buildで作成されたwheel file.

    Returns:
        None: archive contentを検証して完了し、呼び出し側へ値を返さない.

    Raises:
        RuntimeError: 必須memberが欠落するか、生成cacheなどのunexpected memberが含まれる場合.
    """
    with zipfile.ZipFile(wheel_path) as wheel_archive:
        member_names = wheel_archive.namelist()

    native_extensions = [
        member_name
        for member_name in member_names
        if member_name.startswith("athena_crypto/athena_crypto")
        and Path(member_name).suffix in {".dylib", ".pyd", ".so"}
    ]
    required_members = {
        WHEEL_PACKAGE_SOURCE_PATH,
        WHEEL_STUB_PATH,
        WHEEL_NATIVE_STUB_PATH,
        WHEEL_TYPED_MARKER_PATH,
    }
    missing_members = sorted(required_members.difference(member_names))
    package_members = {
        member_name
        for member_name in member_names
        if member_name.startswith("athena_crypto/") and not member_name.endswith("/")
    }
    unexpected_members = sorted(package_members.difference(required_members, native_extensions))
    if len(native_extensions) != 1 or missing_members or unexpected_members:
        message = (
            "Wheel artifact is incomplete or contaminated: "
            f"native_extensions={native_extensions!r}, missing_members={missing_members!r}, "
            f"unexpected_members={unexpected_members!r}"
        )
        raise RuntimeError(message)


def _venv_python(venv_root: Path) -> Path:
    """Current platformのvirtual environment Python executableを返す.

    Args:
        venv_root (Path): `venv` moduleで作成したconsumer virtual environment root.

    Returns:
        Path: wheel installとconsumer checksを実行するPython executable path.

    Raises:
        RuntimeError: virtual environmentがPython executableを作成しなかった場合.
    """
    executable_name = "python.exe" if os.name == "nt" else "python"
    executable_directory = "Scripts" if os.name == "nt" else "bin"
    python_path = venv_root / executable_directory / executable_name
    if not python_path.is_file():
        message = f"Consumer venv Python executable is missing: {python_path}"
        raise RuntimeError(message)
    return python_path


def _verify_installed_native_tests(
    consumer_python: Path,
    consumer_venv: Path,
    environment: Mapping[str, str],
    *,
    tests_directory: Path | None = None,
) -> None:
    """Package-owned unittestをwheel-only consumer venvから実行する.

    Args:
        consumer_python (Path): wheelだけをinstallしたconsumer Python executable.
        consumer_venv (Path): native module load locationをtestへ渡すconsumer venv root.
        environment (Mapping[str, str]): source treeを除去したchild environment mapping.
        tests_directory (Path | None): discovery対象のpackage-owned test directory. Noneの場合は
            標準の`tests` directoryを使用する.

    Returns:
        None: package-owned native behavior testsを成功させて完了する.

    Raises:
        RuntimeError: test commandが失敗するか、native behavior testを一件も発見できない場合.
    """
    test_environment = dict(environment)
    test_environment["ATHENA_CRYPTO_CONSUMER_VENV"] = str(consumer_venv)
    native_tests_directory = tests_directory or PACKAGE_ROOT / "tests"
    native_test_command = [
        str(consumer_python),
        "-m",
        "unittest",
        "discover",
        "-s",
        str(native_tests_directory),
        "-p",
        "test_*.py",
    ]
    completed_process = _run_command(
        native_test_command,
        cwd=consumer_venv,
        environment=test_environment,
        allow_failure=True,
    )
    test_output = f"{completed_process.stdout}\n{completed_process.stderr}"
    if "Ran 0 tests" in test_output:
        message = f"No package-owned native tests were discovered: {native_tests_directory}"
        raise RuntimeError(message)
    if completed_process.returncode != 0:
        raise _command_failure(native_test_command, completed_process)


def _verify_type_aware_consumer(
    consumer_root: Path,
    consumer_python: Path,
    environment: Mapping[str, str],
) -> None:
    """Public stubを使うisolated consumerのtype checkを実行する.

    Args:
        consumer_root (Path): type-aware consumer sourceを置く一時directory.
        consumer_python (Path): wheelだけをinstallしたconsumer Python executable.
        environment (Mapping[str, str]): source treeを除去したchild environment mapping.

    Returns:
        None: consumerがpublic type informationを解決できることを検証して完了する.

    Raises:
        RuntimeError: basedpyright executableがNix development environmentにない場合.
    """
    type_checker = shutil.which("basedpyright")
    if type_checker is None:
        msg = "basedpyright must be available in the development environment"
        raise RuntimeError(msg)

    consumer_source = consumer_root / "type_consumer.py"
    consumer_module_source = '''"""athena_crypto public typing artifact consumer."""

from typing import assert_type

import athena_crypto

result = athena_crypto.decrypt_score_payload(b"encrypted", b"0" * 32, None)
_ = assert_type(result, tuple[str, bool])
_ = assert_type(result[0], str)
_ = assert_type(result[1], bool)
defaulted_result = athena_crypto.decrypt_score_payload(b"encrypted", b"0" * 32)
_ = assert_type(defaulted_result, tuple[str, bool])
'''
    _ = consumer_source.write_text(
        consumer_module_source,
        encoding="utf-8",
    )
    _ = _run_command(
        [type_checker, "--pythonpath", str(consumer_python), str(consumer_source)],
        cwd=consumer_root,
        environment=environment,
    )


def main() -> None:
    """Clean wheelのarchive、native behavior、public type artifactを順に検証する.

    Returns:
        None: すべてのartifact contractが成功した場合に検証結果を標準出力へ報告する.
    """
    environment = _clean_environment()
    with tempfile.TemporaryDirectory(prefix="athena-crypto-artifact-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        cargo_target = temporary_root / "cargo-target"
        wheels_directory = temporary_root / "wheels"
        consumer_venv = temporary_root / "consumer-venv"
        consumer_root = temporary_root / "consumer"
        consumer_root.mkdir()

        _ = _run_command(
            [
                "cargo",
                "test",
                "--manifest-path",
                str(PACKAGE_ROOT / "Cargo.toml"),
                "--target-dir",
                str(cargo_target),
            ],
            cwd=PACKAGE_ROOT,
            environment=environment,
        )
        build_environment = dict(environment)
        build_environment["CARGO_TARGET_DIR"] = str(cargo_target)
        _ = _run_command(
            [
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(wheels_directory),
                str(PACKAGE_ROOT),
            ],
            cwd=PACKAGE_ROOT,
            environment=build_environment,
        )
        wheel_path = _single_wheel(wheels_directory)
        _verify_wheel_archive(wheel_path)

        _ = _run_command(
            [sys.executable, "-m", "venv", str(consumer_venv)],
            cwd=consumer_root,
            environment=environment,
        )
        consumer_python = _venv_python(consumer_venv)
        _ = _run_command(
            [
                str(consumer_python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel_path),
            ],
            cwd=consumer_root,
            environment=environment,
        )
        _verify_installed_native_tests(consumer_python, consumer_venv, environment)
        _verify_type_aware_consumer(consumer_root, consumer_python, environment)

    print("athena_crypto wheel artifact verification passed")


if __name__ == "__main__":
    main()
