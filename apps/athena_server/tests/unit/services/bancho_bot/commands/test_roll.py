"""BanchoBot の !roll command を検証する test module.

channel と PM の response format および CommandContext だけに依存する契約を対象とする.
"""

from __future__ import annotations

from unittest import mock

import pytest

from osu_server.domain.chat.commands import CommandContext, CommandDestination
from osu_server.services.commands.chat.bancho_bot.commands.general import setup_general
from osu_server.services.commands.chat.bancho_bot.registry import (
    CommandDefinition,
    CommandRegistry,
)


@pytest.fixture
def roll_def() -> CommandDefinition:
    """登録済みの roll definition を general command registry から提供する.

    Returns:
        CommandDefinition: handler 呼び出しに使用する roll command definition.
    """
    registry = CommandRegistry()
    setup_general(registry)
    resolved = registry.resolve("roll")
    assert resolved is not None
    return resolved


def _make_context(
    *,
    sender_id: int = 1,
    sender_name: str = "Player",
    target: str = "#osu",
    command_name: str = "roll",
    args: tuple[str, ...] = (),
    destination: CommandDestination | None = None,
) -> CommandContext:
    """Roll command test 用の最小 command context を生成する.

    Args:
        sender_id (int): command を実行する sender の識別子.
        sender_name (str): response へ表示する sender 名.
        target (str): command の送信先 channel または PM 相手.
        command_name (str): context に記録する command 名.
        args (tuple[str, ...]): parser が渡す command argument の順序付き列.
        destination (CommandDestination | None): 明示する送信先. None の場合は target から推測する.

    Returns:
        CommandContext: roll handler へ渡す command context.
    """
    if destination is None:
        destination = (
            CommandDestination.CHANNEL if target.startswith("#") else CommandDestination.PM
        )
    return CommandContext(
        sender_id=sender_id,
        sender_name=sender_name,
        target=target,
        command_name=command_name,
        args=args,
        destination=destination,
        available_commands=(),
    )


class TestRollNoArgs:
    """引数を持たない !roll の既定値を検証する.

    最大値を指定しない場合に handler が 100 を使用する契約を対象とする.
    """

    async def test_no_args_default_max_100(self, roll_def: CommandDefinition) -> None:
        """引数なしの !roll が既定最大値の response を返すことを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: 決定済み乱数を含む既定 format の response を検証して完了する.
        """
        ctx = _make_context()
        with mock.patch("random.randint", return_value=42):
            result = await roll_def.handler(ctx)

        assert result is not None
        assert result == "Player rolls 42 point(s)"

    async def test_no_args_response_contains_sender_name(
        self, roll_def: CommandDefinition
    ) -> None:
        """引数なしの response が sender_name を含むことを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: 指定 sender 名を含む response を検証して完了する.
        """
        ctx = _make_context(sender_name="Alice")
        with mock.patch("random.randint", return_value=7):
            result = await roll_def.handler(ctx)

        assert result == "Alice rolls 7 point(s)"


class TestRollWithNumericArg:
    """数値 argument を持つ !roll の最大値処理を検証する.

    先頭 argument が乱数上限と response format に反映される契約を対象とする.
    """

    async def test_numeric_arg_custom_max(self, roll_def: CommandDefinition) -> None:
        """数値 argument が custom 最大値を設定することを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: custom 最大値で得た response format を検証して完了する.
        """
        ctx = _make_context(args=("50",))
        with mock.patch("random.randint", return_value=23):
            result = await roll_def.handler(ctx)

        assert result == "Player rolls 23 point(s)"

    async def test_numeric_arg_10(self, roll_def: CommandDefinition) -> None:
        """10 を指定した !roll が上限 10 を使うことを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: 上限 10 の決定済み response を検証して完了する.
        """
        ctx = _make_context(args=("10",))
        with mock.patch("random.randint", return_value=5):
            result = await roll_def.handler(ctx)

        assert result == "Player rolls 5 point(s)"

    async def test_numeric_arg_1(self, roll_def: CommandDefinition) -> None:
        """1 を指定した !roll が上限 1 を使うことを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: 上限 1 の決定済み response を検証して完了する.
        """
        ctx = _make_context(args=("1",))
        with mock.patch("random.randint", return_value=1):
            result = await roll_def.handler(ctx)

        assert result == "Player rolls 1 point(s)"

    async def test_clamps_zero_to_one(self, roll_def: CommandDefinition) -> None:
        """0 を指定した !roll が上限を 1 へ clamp することを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: randint の下限と clamp 後の上限を検証して完了する.
        """
        ctx = _make_context(args=("0",))
        with mock.patch("random.randint", return_value=0) as mock_randint:
            result = await roll_def.handler(ctx)
            mock_randint.assert_called_once_with(0, 1)

        assert result == "Player rolls 0 point(s)"

    async def test_random_uses_correct_max(self, roll_def: CommandDefinition) -> None:
        """数値 argument が randint の上限に渡されることを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: parsed 最大値を持つ randint 呼び出しを検証して完了する.
        """
        ctx = _make_context(args=("75",))
        with mock.patch("random.randint", return_value=30) as mock_randint:
            _ = await roll_def.handler(ctx)
            mock_randint.assert_called_once_with(0, 75)


class TestRollWithNonNumericArg:
    """数値でない argument を持つ !roll の既定値処理を検証する.

    非数値の先頭 argument を無視して既定上限を使う契約を対象とする.
    """

    async def test_non_numeric_first_arg_defaults(self, roll_def: CommandDefinition) -> None:
        """非数値の先頭 argument が既定上限へ fallback することを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: 上限 100 の randint 呼び出しと response を検証して完了する.
        """
        ctx = _make_context(args=("abc",))
        with mock.patch("random.randint", return_value=50) as mock_randint:
            result = await roll_def.handler(ctx)
            mock_randint.assert_called_once_with(0, 100)

        assert result == "Player rolls 50 point(s)"

    async def test_multiple_args_only_first_used(self, roll_def: CommandDefinition) -> None:
        """複数 argument のうち先頭だけを最大値に使うことを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: 先頭 argument を上限にした response を検証して完了する.
        """
        ctx = _make_context(args=("50", "100"))
        with mock.patch("random.randint", return_value=25) as mock_randint:
            result = await roll_def.handler(ctx)
            mock_randint.assert_called_once_with(0, 50)

        assert result == "Player rolls 25 point(s)"


class TestRollPMResponse:
    """PM 経由の !roll response format を検証する.

    target routing を CommandService が担い handler の文字列 format が変わらない契約を対象とする.
    """

    async def test_pm_response_format_unchanged(self, roll_def: CommandDefinition) -> None:
        """PM command が channel と同じ response format を返すことを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: PM target に対する player-visible response を検証して完了する.
        """
        ctx = _make_context(target="BanchoBot")
        with mock.patch("random.randint", return_value=99):
            result = await roll_def.handler(ctx)

        assert result == "Player rolls 99 point(s)"


class TestRollRegisteredAsCommandDefinition:
    """Roll の CommandDefinition 登録契約を検証する.

    decorator が生成する metadata と handler invocation の両方を対象とする.
    """

    def test_roll_is_command_definition(self, roll_def: CommandDefinition) -> None:
        """Roll が有効な CommandDefinition として登録されることを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: metadata の name と description と usage を検証して完了する.
        """
        assert isinstance(roll_def, CommandDefinition)
        assert roll_def.metadata.name == "roll"
        assert roll_def.metadata.description == "Roll a random number"
        assert roll_def.metadata.usage == "!roll [max]"

    async def test_invocation_through_decorated_handler(self, roll_def: CommandDefinition) -> None:
        """Decorator 経由で取得した roll handler が応答することを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: sender と custom 上限を含む response を検証して完了する.
        """
        ctx = _make_context(sender_name="Tester", args=("20",))
        with mock.patch("random.randint", return_value=15):
            result = await roll_def.handler(ctx)

        assert result == "Tester rolls 15 point(s)"


class TestRollIndependence:
    """Roll handler の CommandContext 依存性を検証する.

    session と database を参照せず context の field だけで応答する契約を対象とする.
    """

    async def test_no_session_access(self, roll_def: CommandDefinition) -> None:
        """Roll handler が session や database なしで応答することを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: context だけから得る response を検証して完了する.
        """
        ctx = _make_context(sender_name="Indie")
        with mock.patch("random.randint", return_value=42):
            result = await roll_def.handler(ctx)

        assert result == "Indie rolls 42 point(s)"

    async def test_no_available_commands_needed(self, roll_def: CommandDefinition) -> None:
        """Roll handler が available_commands を必要としないことを検証する.

        Args:
            roll_def (CommandDefinition): 登録済み roll command definition.

        Returns:
            None: 空の command list でも handler が応答することを検証して完了する.
        """
        ctx = _make_context()
        with mock.patch("random.randint", return_value=3):
            result = await roll_def.handler(ctx)

        assert result is not None
