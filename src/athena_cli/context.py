from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping


EnvironmentName = Literal["development", "test", "production"]
SUPPORTED_ENVIRONMENTS: frozenset[EnvironmentName] = frozenset(
    {"development", "test", "production"}
)
SUPPORTED_ENVIRONMENT_LABEL = "development, test, production"
DEFAULT_ENVIRONMENT: EnvironmentName = "development"
ENVIRONMENT_VARIABLE = "ENVIRONMENT"


class UnsupportedEnvironmentError(ValueError):
    def __init__(self, environment: str) -> None:
        self.environment: str
        self.environment = environment
        message = f"Unsupported environment {environment!r}."
        message = f"{message} Supported environments: {SUPPORTED_ENVIRONMENT_LABEL}."
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CliContext:
    environment: EnvironmentName
    subprocess_environment: dict[str, str]


def resolve_context(
    *,
    selected_environment: str | None,
    process_environment: Mapping[str, str],
) -> CliContext:
    environment = _resolve_environment_name(selected_environment, process_environment)
    subprocess_environment = dict(process_environment)
    subprocess_environment[ENVIRONMENT_VARIABLE] = environment
    return CliContext(environment=environment, subprocess_environment=subprocess_environment)


def _resolve_environment_name(
    selected_environment: str | None,
    process_environment: Mapping[str, str],
) -> EnvironmentName:
    candidate = (
        selected_environment
        if selected_environment is not None
        else process_environment.get(ENVIRONMENT_VARIABLE, DEFAULT_ENVIRONMENT)
    ).lower()
    if candidate not in SUPPORTED_ENVIRONMENTS:
        raise UnsupportedEnvironmentError(candidate)
    return candidate
