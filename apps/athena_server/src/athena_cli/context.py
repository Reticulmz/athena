"""CLI commandが共有するenvironment contextを提供する."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.config import (
    DEFAULT_ENVIRONMENT,
    ENVIRONMENT_VARIABLE,
    SUPPORTED_ENVIRONMENT_LABEL,
    SUPPORTED_ENVIRONMENTS,
    EnvironmentName,
    UnsupportedEnvironmentError,
    validate_environment_name,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping


__all__ = (
    "DEFAULT_ENVIRONMENT",
    "ENVIRONMENT_VARIABLE",
    "SUPPORTED_ENVIRONMENTS",
    "SUPPORTED_ENVIRONMENT_LABEL",
    "CliContext",
    "EnvironmentName",
    "UnsupportedEnvironmentError",
    "resolve_context",
    "selected_environment_variable",
)


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
    )
    return validate_environment_name(candidate)


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
