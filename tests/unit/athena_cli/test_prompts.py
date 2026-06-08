from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from athena_cli.env.dsn import DatabaseConnectionParts, ValkeyConnectionParts
from athena_cli.prompts import InitSection, OsuApiPromptResult, PromptAdapter, PromptChoice

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(slots=True)
class FakePromptProvider:
    checkbox_results: list[object] = field(default_factory=list)
    text_results: list[object] = field(default_factory=list)
    secret_results: list[object] = field(default_factory=list)
    confirm_results: list[object] = field(default_factory=list)

    def checkbox(self, *, message: str, choices: Sequence[PromptChoice]) -> object:
        _ = message
        _ = choices
        return self.checkbox_results.pop(0)

    def text(self, *, message: str, default: str | None = None) -> object:
        _ = message
        _ = default
        return self.text_results.pop(0)

    def secret(self, *, message: str) -> object:
        _ = message
        return self.secret_results.pop(0)

    def confirm(self, *, message: str, default: bool = False) -> object:
        _ = message
        _ = default
        return self.confirm_results.pop(0)


def test_select_sections_returns_typed_sections() -> None:
    adapter = PromptAdapter(provider=FakePromptProvider(checkbox_results=[["database", "valkey"]]))

    assert adapter.select_sections() == ("database", "valkey")


def test_collect_database_parts_returns_typed_result() -> None:
    adapter = PromptAdapter(
        provider=FakePromptProvider(
            text_results=["localhost", "5432", "athena", "athena"],
            secret_results=["db-password"],
        )
    )

    assert adapter.collect_database_parts() == DatabaseConnectionParts(
        host="localhost",
        port=5432,
        database="athena",
        username="athena",
        password="db-password",
    )


def test_collect_valkey_parts_returns_typed_result() -> None:
    adapter = PromptAdapter(
        provider=FakePromptProvider(
            text_results=["localhost", "6379", "2", "default"],
            secret_results=["valkey-password"],
        )
    )

    assert adapter.collect_valkey_parts() == ValkeyConnectionParts(
        host="localhost",
        port=6379,
        database=2,
        username="default",
        password="valkey-password",
    )


def test_collect_osu_api_config_skips_credentials_when_disabled() -> None:
    adapter = PromptAdapter(provider=FakePromptProvider(confirm_results=[False]))

    assert adapter.collect_osu_api_config() == OsuApiPromptResult(
        enabled=False,
        client_id=None,
        client_secret=None,
    )


def test_collect_osu_api_config_collects_secret_credentials_when_enabled() -> None:
    adapter = PromptAdapter(
        provider=FakePromptProvider(
            text_results=["1234"],
            secret_results=["client-secret"],
            confirm_results=[True],
        )
    )

    assert adapter.collect_osu_api_config() == OsuApiPromptResult(
        enabled=True,
        client_id="1234",
        client_secret="client-secret",
    )


def test_confirm_returns_bool() -> None:
    adapter = PromptAdapter(provider=FakePromptProvider(confirm_results=[True]))

    assert adapter.confirm("overwrite?") is True


def test_prompt_choices_are_typed() -> None:
    section: InitSection = "osu_api"

    assert section == "osu_api"
