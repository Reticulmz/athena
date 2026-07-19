"""prompt adapterがprovider結果を型付きCLI入力へ変換する契約を検証する."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from athena_cli.env.dsn import DatabaseConnectionParts, ValkeyConnectionParts
from athena_cli.errors import CliUserError
from athena_cli.prompts import InitSection, OsuApiPromptResult, PromptAdapter, PromptChoice

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(slots=True)
class FakePromptProvider:
    """決めた順番の結果を返すPromptProvider fakeを提供する.

    Attributes:
        checkbox_results (list[object]): checkbox呼び出しごとに返す未検証結果.
        text_results (list[object]): text呼び出しごとに返す未検証結果.
        secret_results (list[object]): secret呼び出しごとに返す未検証結果.
        confirm_results (list[object]): confirm呼び出しごとに返す未検証結果.
    """

    checkbox_results: list[object] = field(default_factory=list)
    text_results: list[object] = field(default_factory=list)
    secret_results: list[object] = field(default_factory=list)
    confirm_results: list[object] = field(default_factory=list)

    def checkbox(self, *, message: str, choices: Sequence[PromptChoice]) -> object:
        """次のcheckbox結果を返しprompt内容は検証しない.

        Args:
            message (str): adapterから渡される表示message.
            choices (Sequence[PromptChoice]): adapterから渡される選択肢.

        Returns:
            object: 事前設定した次のcheckbox結果.
        """
        _ = message
        _ = choices
        return self.checkbox_results.pop(0)

    def text(self, *, message: str, default: str | None = None) -> object:
        """次のtext結果を返しprompt内容は検証しない.

        Args:
            message (str): adapterから渡される表示message.
            default (str | None): adapterから渡されるoptionalな既定値.

        Returns:
            object: 事前設定した次のtext結果.
        """
        _ = message
        _ = default
        return self.text_results.pop(0)

    def secret(self, *, message: str) -> object:
        """次のsecret結果を返しprompt内容は検証しない.

        Args:
            message (str): adapterから渡される表示message.

        Returns:
            object: 事前設定した次のsecret結果.
        """
        _ = message
        return self.secret_results.pop(0)

    def confirm(self, *, message: str, default: bool = False) -> object:
        """次のconfirmation結果を返しprompt内容は検証しない.

        Args:
            message (str): adapterから渡される表示message.
            default (bool): adapterから渡される既定confirmation値.

        Returns:
            object: 事前設定した次のconfirmation結果.
        """
        _ = message
        _ = default
        return self.confirm_results.pop(0)


def test_select_sections_returns_typed_sections() -> None:
    """checkboxの文字列結果がInitSection tupleへ変換されることを検証する.

    Returns:
        None: 型付きsection tupleを検証して完了する. 呼び出し側へ値を返さない.
    """
    adapter = PromptAdapter(provider=FakePromptProvider(checkbox_results=[["database", "valkey"]]))

    assert adapter.select_sections() == ("database", "valkey")


def test_collect_database_parts_returns_typed_result() -> None:
    """Database promptの文字列入力がDatabaseConnectionPartsへ変換されることを検証する.

    Returns:
        None: hostとportと認証情報を検証して完了する. 呼び出し側へ値を返さない.
    """
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
    """Valkey promptの文字列入力がValkeyConnectionPartsへ変換されることを検証する.

    Returns:
        None: hostとdatabaseと認証情報を検証して完了する. 呼び出し側へ値を返さない.
    """
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
    """Official osu! APIを無効化した場合にcredentialを要求しないことを検証する.

    Returns:
        None: 無効化状態とNone credentialsを検証して完了する. 呼び出し側へ値を返さない.
    """
    adapter = PromptAdapter(provider=FakePromptProvider(confirm_results=[False]))

    assert adapter.collect_osu_api_config() == OsuApiPromptResult(
        enabled=False,
        client_id=None,
        client_secret=None,
    )


def test_collect_osu_api_config_collects_secret_credentials_when_enabled() -> None:
    """Official osu! APIを有効化した場合に入力credentialを収集することを検証する.

    Returns:
        None: 有効化状態と入力credentialを検証して完了する. 呼び出し側へ値を返さない.
    """
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
    """boolのconfirmation結果をそのまま返すことを検証する.

    Returns:
        None: Trueのconfirmation結果を検証して完了する. 呼び出し側へ値を返さない.
    """
    adapter = PromptAdapter(provider=FakePromptProvider(confirm_results=[True]))

    assert adapter.confirm("overwrite?") is True


def test_collect_confirmed_secret_returns_secret_when_values_match() -> None:
    """一致する2回のsecret入力だけを返すことを検証する.

    Returns:
        None: 確認済みsecretを検証して完了する. 呼び出し側へ値を返さない.
    """
    adapter = PromptAdapter(
        provider=FakePromptProvider(secret_results=["new-password", "new-password"])
    )

    assert (
        adapter.collect_confirmed_secret(
            message="New password",
            confirmation_message="Confirm new password",
        )
        == "new-password"
    )


def test_collect_confirmed_secret_rejects_mismatched_values() -> None:
    """不一致の2回のsecret入力をCliUserErrorで拒否することを検証する.

    Returns:
        None: 例外のmessageを検証して完了する. 呼び出し側へ値を返さない.
    """
    adapter = PromptAdapter(provider=FakePromptProvider(secret_results=["one", "two"]))

    with pytest.raises(CliUserError, match=r"Secret confirmation did not match\."):
        _ = adapter.collect_confirmed_secret(
            message="New password",
            confirmation_message="Confirm new password",
        )


def test_prompt_choices_are_typed() -> None:
    """InitSection型がosu_apiという有効な選択肢を表せることを検証する.

    Returns:
        None: 型付きchoice値を検証して完了する. 呼び出し側へ値を返さない.
    """
    section: InitSection = "osu_api"

    assert section == "osu_api"
