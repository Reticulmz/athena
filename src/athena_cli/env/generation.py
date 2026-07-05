from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from athena_cli.env.schema import get_config_env_metadata
from athena_cli.errors import CliUserError
from athena_cli.presentation import mask_secret
from osu_server.config import AppConfig

if TYPE_CHECKING:
    from collections.abc import Mapping

    from athena_cli.context import EnvironmentName


@dataclass(frozen=True, slots=True)
class EnvGenerationInput:
    environment: EnvironmentName
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class EnvGenerationResult:
    content: str
    masked_summary: tuple[str, ...]


class MissingEnvValuesError(CliUserError):
    def __init__(self, missing_values: tuple[str, ...]) -> None:
        self.missing_values: tuple[str, ...] = missing_values
        joined_values = ", ".join(missing_values)
        super().__init__(f"Missing required environment values: {joined_values}")


def generate_env_content(generation_input: EnvGenerationInput) -> EnvGenerationResult:
    values = _collect_values(generation_input)
    _validate_app_config(values)
    lines = tuple(f"{env_var}={value}" for env_var, value in values.items())
    masked_summary = tuple(
        _format_summary_line(env_var, value)
        for env_var, value in values.items()
        if _is_secret_env_var(env_var)
    )
    return EnvGenerationResult(content="\n".join(lines) + "\n", masked_summary=masked_summary)


def _collect_values(generation_input: EnvGenerationInput) -> dict[str, str]:
    values: dict[str, str] = {}
    missing_values: list[str] = []
    for field in get_config_env_metadata():
        value = generation_input.values.get(field.env_var)
        if field.env_var == "ENVIRONMENT":
            value = generation_input.environment
        if value is None:
            if field.empty_value_is_unset and field.default in (None, ""):
                continue
            value = field.default
        if field.empty_value_is_unset and value == "":
            continue
        if field.required and not value:
            missing_values.append(field.env_var)
            continue
        values[field.env_var] = value or ""
    if missing_values:
        raise MissingEnvValuesError(tuple(missing_values))
    return values


def _validate_app_config(values: Mapping[str, str]) -> None:
    field_values: dict[str, object] = {}
    for field in get_config_env_metadata():
        if field.env_var not in values:
            continue
        value = values[field.env_var]
        if field.empty_value_is_unset and value == "":
            continue
        field_values[field.field_name] = _parse_list_value(value) if field.list_like else value
    _ = AppConfig.model_validate(field_values)


def _parse_list_value(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _format_summary_line(env_var: str, value: str) -> str:
    return f"{env_var}={mask_secret(value)}"


def _is_secret_env_var(env_var: str) -> bool:
    return any(part in env_var for part in ("PASSWORD", "SECRET", "ACCESS_KEY"))
