"""BanchoBot の組み込み command catalog を検証する test module.

registry が登録する command の構成と help response の外部契約を対象とする.
"""

from __future__ import annotations

from unittest import mock

from osu_server.domain.chat.commands import CommandContext, CommandDestination
from osu_server.domain.identity.authorization import Privileges
from osu_server.services.commands.chat.bancho_bot.commands import create_builtin_registry
from osu_server.services.commands.chat.bancho_bot.registry import CommandRegistry


def _make_help_ctx(registry: CommandRegistry) -> CommandContext:
    """組み込み registry の command を含む help 用 context を生成する.

    Args:
        registry (CommandRegistry): 利用可能な command を取得する registry.

    Returns:
        CommandContext: help handler へ渡す command context.
    """
    return CommandContext(
        sender_id=1,
        sender_name="testuser",
        target="#osu",
        command_name="help",
        args=(),
        destination=CommandDestination.CHANNEL,
        available_commands=registry.commands(),
    )


class TestBuiltinRegistryStructure:
    """組み込み registry の command 構成を検証する.

    player-visible command が roll と help に限定される契約を対象とする.
    """

    def test_returns_command_registry(self) -> None:
        """組み込み catalog が CommandRegistry instance を返すことを検証する.

        Returns:
            None: 生成結果の registry 型を検証して完了する.
        """
        registry = create_builtin_registry()
        assert isinstance(registry, CommandRegistry)

    def test_exactly_two_commands(self) -> None:
        """組み込み catalog が 2 個だけの command を登録することを検証する.

        Returns:
            None: 登録済み command 数を検証して完了する.
        """
        registry = create_builtin_registry()
        all_cmds = registry.commands()
        assert len(all_cmds) == 2

    def test_registration_order_roll_then_help(self) -> None:
        """組み込み catalog で roll が help より先に登録される順序契約を検証する.

        Returns:
            None: command metadata の登録順を検証して完了する.
        """
        registry = create_builtin_registry()
        all_cmds = registry.commands()
        assert all_cmds[0].name == "roll"
        assert all_cmds[1].name == "help"

    def test_both_commands_are_public(self) -> None:
        """組み込み catalog の roll と help が特権を要求しないことを検証する.

        Returns:
            None: 両 command の required_privileges を検証して完了する.
        """
        registry = create_builtin_registry()
        roll_def = registry.resolve("roll")
        help_def = registry.resolve("help")
        assert roll_def is not None
        assert help_def is not None
        assert roll_def.metadata.required_privileges == Privileges.NONE
        assert help_def.metadata.required_privileges == Privileges.NONE

    def test_no_other_commands_registered(self) -> None:
        """組み込み catalog で roll と help 以外の command 名を解決できないことを検証する.

        Returns:
            None: 未登録名の resolve 結果を検証して完了する.
        """
        registry = create_builtin_registry()
        assert registry.resolve("unknown") is None
        assert registry.resolve("admin") is None
        assert registry.resolve("") is None

    def test_roll_resolves_case_insensitively(self) -> None:
        """組み込み catalog の roll が大文字小文字を区別せず解決されることを検証する.

        Returns:
            None: 複数の大文字小文字表記を検証して完了する.
        """
        registry = create_builtin_registry()
        assert registry.resolve("ROLL") is not None
        assert registry.resolve("Roll") is not None
        assert registry.resolve("rOlL") is not None

    def test_help_resolves_case_insensitively(self) -> None:
        """組み込み catalog の help が大文字小文字を区別せず解決されることを検証する.

        Returns:
            None: 複数の大文字小文字表記を検証して完了する.
        """
        registry = create_builtin_registry()
        assert registry.resolve("HELP") is not None
        assert registry.resolve("Help") is not None


class TestBuiltinRegistryHelpOutput:
    """組み込み registry から得る help output を検証する.

    登録済み command と登録順が player-visible response へ反映される契約を対象とする.
    """

    async def test_help_output_matches_expected(self) -> None:
        """組み込み help handler が期待する一覧 response を返すことを検証する.

        Returns:
            None: roll と help を含む response text を検証して完了する.
        """
        registry = create_builtin_registry()
        help_def = registry.resolve("help")
        assert help_def is not None
        ctx = _make_help_ctx(registry)
        result = await help_def.handler(ctx)
        assert result == "Available commands: !roll, !help"

    def test_help_output_uses_registration_order(self) -> None:
        """組み込み help output 用の command 列が登録順を保つことを検証する.

        Returns:
            None: 組み込み catalog の command 名順を検証して完了する.
        """
        registry = create_builtin_registry()
        all_cmds = registry.commands()
        names = [cmd.name for cmd in all_cmds]
        assert names == ["roll", "help"]


class TestBuiltinRegistryHandlers:
    """組み込み command handler の接続を検証する.

    registry から解決した handler が command ごとの response 契約を満たすことを対象とする.
    """

    async def test_roll_handler_produces_correct_response(self) -> None:
        """組み込み roll handler が決定済み乱数の response を返すことを検証する.

        Returns:
            None: sender 名と乱数を含む roll response を検証して完了する.
        """
        registry = create_builtin_registry()
        roll_def = registry.resolve("roll")
        assert roll_def is not None

        ctx = CommandContext(
            sender_id=1,
            sender_name="Test",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=registry.commands(),
        )
        with mock.patch("random.randint", return_value=50):
            result = await roll_def.handler(ctx)

        assert result == "Test rolls 50 point(s)"

    async def test_help_handler_produces_correct_output(self) -> None:
        """組み込み help handler が登録済み command の一覧を返すことを検証する.

        Returns:
            None: player-visible help response を検証して完了する.
        """
        registry = create_builtin_registry()
        help_def = registry.resolve("help")
        assert help_def is not None

        ctx = CommandContext(
            sender_id=1,
            sender_name="Test",
            target="#osu",
            command_name="help",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=registry.commands(),
        )
        result = await help_def.handler(ctx)
        assert result == "Available commands: !roll, !help"
