from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, cast

from athena_cli.env.dsn import DatabaseConnectionParts, ValkeyConnectionParts
from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


InitSection = Literal["database", "valkey", "osu_api"]
_INIT_SECTIONS: frozenset[InitSection] = frozenset({"database", "valkey", "osu_api"})


@dataclass(frozen=True, slots=True)
class PromptChoice:
    name: str
    value: str


class PromptProvider(Protocol):
    def checkbox(self, *, message: str, choices: Sequence[PromptChoice]) -> object: ...

    def text(self, *, message: str, default: str | None = None) -> object: ...

    def secret(self, *, message: str) -> object: ...

    def confirm(self, *, message: str, default: bool = False) -> object: ...


class ExecutablePrompt(Protocol):
    def execute(self) -> object: ...


class InquirerPyPromptProvider:
    def checkbox(self, *, message: str, choices: Sequence[PromptChoice]) -> object:
        prompt_choices = [{"name": choice.name, "value": choice.value} for choice in choices]
        prompt = _get_prompt_factory("checkbox")(message=message, choices=prompt_choices)
        return _execute_prompt(prompt)

    def text(self, *, message: str, default: str | None = None) -> object:
        prompt = _get_prompt_factory("text")(message=message, default=default or "")
        return _execute_prompt(prompt)

    def secret(self, *, message: str) -> object:
        prompt = _get_prompt_factory("secret")(message=message)
        return _execute_prompt(prompt)

    def confirm(self, *, message: str, default: bool = False) -> object:
        prompt = _get_prompt_factory("confirm")(message=message, default=default)
        return _execute_prompt(prompt)


@dataclass(frozen=True, slots=True)
class OsuApiPromptResult:
    enabled: bool
    client_id: str | None
    client_secret: str | None


@dataclass(frozen=True, slots=True)
class PromptAdapter:
    provider: PromptProvider = field(default_factory=InquirerPyPromptProvider)

    def select_sections(self) -> tuple[InitSection, ...]:
        raw_result = self.provider.checkbox(
            message="Select configuration sections",
            choices=(
                PromptChoice(name="Database", value="database"),
                PromptChoice(name="Valkey", value="valkey"),
                PromptChoice(name="osu! API", value="osu_api"),
            ),
        )
        return tuple(_coerce_section(value) for value in _coerce_string_sequence(raw_result))

    def collect_database_parts(self) -> DatabaseConnectionParts:
        return DatabaseConnectionParts(
            host=_coerce_string(self.provider.text(message="Database host", default="localhost")),
            port=_coerce_int(self.provider.text(message="Database port", default="5432")),
            database=_coerce_string(self.provider.text(message="Database name")),
            username=_coerce_string(self.provider.text(message="Database username")),
            password=_coerce_string(self.provider.secret(message="Database password")),
        )

    def collect_valkey_parts(self) -> ValkeyConnectionParts:
        return ValkeyConnectionParts(
            host=_coerce_string(self.provider.text(message="Valkey host", default="localhost")),
            port=_coerce_int(self.provider.text(message="Valkey port", default="6379")),
            database=_coerce_int(self.provider.text(message="Valkey database", default="0")),
            username=_coerce_optional_string(self.provider.text(message="Valkey username")),
            password=_coerce_optional_string(self.provider.secret(message="Valkey password")),
        )

    def collect_osu_api_config(self) -> OsuApiPromptResult:
        enabled = self.confirm("Enable official osu! API sources?")
        if not enabled:
            return OsuApiPromptResult(enabled=False, client_id=None, client_secret=None)
        return OsuApiPromptResult(
            enabled=True,
            client_id=_coerce_string(self.provider.text(message="osu! API client ID")),
            client_secret=_coerce_string(self.provider.secret(message="osu! API client secret")),
        )

    def confirm(self, message: str, *, default: bool = False) -> bool:
        raw_result = self.provider.confirm(message=message, default=default)
        if not isinstance(raw_result, bool):
            raise CliUserError("Confirmation prompt returned a non-boolean value.")
        return raw_result


def _coerce_section(value: str) -> InitSection:
    if value not in _INIT_SECTIONS:
        raise CliUserError(f"Unsupported section selected: {value}")
    return value


def _coerce_string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise CliUserError("Section prompt returned an invalid value.")
    raw_items = cast("Sequence[object]", value)
    if not all(isinstance(item, str) for item in raw_items):
        raise CliUserError("Section prompt returned non-string values.")
    return tuple(cast("Sequence[str]", raw_items))


def _coerce_string(value: object) -> str:
    if not isinstance(value, str):
        raise CliUserError("Text prompt returned a non-string value.")
    return value


def _coerce_optional_string(value: object) -> str | None:
    coerced = _coerce_string(value)
    return coerced or None


def _coerce_int(value: object) -> int:
    raw_value = _coerce_string(value)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise CliUserError(f"Expected an integer prompt value, got {raw_value!r}.") from exc


def _get_prompt_factory(name: str) -> Callable[..., object]:
    inquirer_module = importlib.import_module("InquirerPy.inquirer")
    factory = cast("object", getattr(inquirer_module, name))
    if not callable(factory):
        raise CliUserError(f"InquirerPy prompt factory is not callable: {name}")
    return factory


def _execute_prompt(prompt: object) -> object:
    return cast("ExecutablePrompt", prompt).execute()
