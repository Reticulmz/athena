"""CLI commandが共有するenvironment contextを提供する."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping


EnvironmentName = Literal["development", "test", "production"]
SUPPORTED_ENVIRONMENTS: frozenset[EnvironmentName] = frozenset(
    {"development", "test", "production"}
)
SUPPORTED_ENVIRONMENT_LABEL = "development, test, production"
DEFAULT_ENVIRONMENT: EnvironmentName = "development"
ENVIRONMENT_VARIABLE = "ENVIRONMENT"


class UnsupportedEnvironmentError(ValueError):
    """CLIが受け付けないenvironment名を表す.

    Attributes:
        environment (str): validationで拒否した入力値.
    """

    def __init__(self, environment: str) -> None:
        """unsupportedなenvironment名を保持して例外を初期化する.

        Args:
            environment (str): support対象外として検出したenvironment名.
        """
        self.environment: str
        self.environment = environment
        message = f"Unsupported environment {environment!r}."
        message = f"{message} Supported environments: {SUPPORTED_ENVIRONMENT_LABEL}."
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CliContext:
    """CLI commandのenvironmentとsubprocess用環境変数を表す.

    Attributes:
        environment (EnvironmentName): validation済みのtarget environment.
        subprocess_environment (dict[str, str]): ENVIRONMENTを反映したsubprocess用環境変数.
    """

    environment: EnvironmentName
    subprocess_environment: dict[str, str]


def resolve_context(
    *,
    selected_environment: str | None,
    process_environment: Mapping[str, str],
) -> CliContext:
    """選択値とprocess環境からCLI command用contextを解決する.

    Args:
        selected_environment (str | None): command optionで明示したenvironment. 未指定時は
            process環境を参照する.
        process_environment (Mapping[str, str]): 呼び出し元processから受け取る環境変数.

    Returns:
        CliContext: validation済みenvironmentとsubprocessへ渡す環境変数.

    Raises:
        UnsupportedEnvironmentError: 選択値またはprocess環境の値がsupport対象外の場合.
    """
    environment = _resolve_environment_name(selected_environment, process_environment)
    subprocess_environment = dict(process_environment)
    subprocess_environment[ENVIRONMENT_VARIABLE] = environment
    return CliContext(environment=environment, subprocess_environment=subprocess_environment)


def _resolve_environment_name(
    selected_environment: str | None,
    process_environment: Mapping[str, str],
) -> EnvironmentName:
    """選択値またはprocess環境をsupport対象のenvironment名へ正規化する.

    Args:
        selected_environment (str | None): command optionで明示したenvironment.
        process_environment (Mapping[str, str]): ENVIRONMENTを含む可能性がある環境変数.

    Returns:
        EnvironmentName: 小文字化してvalidation済みのenvironment名.

    Raises:
        UnsupportedEnvironmentError: candidateがsupport対象外の場合.
    """
    candidate = (
        selected_environment
        if selected_environment is not None
        else process_environment.get(ENVIRONMENT_VARIABLE, DEFAULT_ENVIRONMENT)
    ).lower()
    if candidate not in SUPPORTED_ENVIRONMENTS:
        raise UnsupportedEnvironmentError(candidate)
    return candidate


@contextmanager
def selected_environment_variable(environment: EnvironmentName) -> Generator[None]:
    """block内だけENVIRONMENTを指定値へ設定するcontext managerを提供する.

    Args:
        environment (EnvironmentName): blockの実行中に設定するenvironment名.

    Yields:
        None: ENVIRONMENTを一時設定したblock制御を呼び出し側へ渡す.

    Notes:
        block終了時には呼び出し前のENVIRONMENT値または未設定状態を復元する.
    """
    previous_environment = os.environ.get(ENVIRONMENT_VARIABLE)
    os.environ[ENVIRONMENT_VARIABLE] = environment
    try:
        yield
    finally:
        if previous_environment is None:
            _ = os.environ.pop(ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[ENVIRONMENT_VARIABLE] = previous_environment
