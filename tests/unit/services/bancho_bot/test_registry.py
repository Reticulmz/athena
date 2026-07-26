"""BanchoBot command registry と decorator contract を検証する test module.

command の登録と解決および metadata の外部契約を対象とする.
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from osu_server.domain.chat.commands import (
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.services.commands.chat.bancho_bot.registry import (
    CommandDefinition,
    CommandRegistry,
    command,
)


class TestCommandDefinition:
    """CommandDefinition の metadata と handler binding を検証する.

    immutable な definition が callable handler を保持する契約を対象とする.
    """

    def test_create_definition(self) -> None:
        """渡した metadata と handler から CommandDefinition を生成できることを検証する.

        Returns:
            None: 渡した metadata と handler の identity を検証して完了する.
        """
        meta = CommandMetadata(name="roll", description="Roll a random number")

        async def handler(_ctx: CommandContext) -> str | None:
            """固定の handler result を返す test double を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: definition が保持する固定 response.
            """
            return "result"

        definition = CommandDefinition(metadata=meta, handler=handler)
        assert definition.metadata == meta
        assert definition.handler is handler

    def test_is_immutable(self) -> None:
        """CommandDefinition の field が immutable であることを検証する.

        Returns:
            None: metadata の再代入が FrozenInstanceError になることを検証して完了する.
        """
        meta = CommandMetadata(name="roll", description="roll")

        async def handler(_ctx: CommandContext) -> str | None:
            """値を返さずに完了する test handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        definition = CommandDefinition(metadata=meta, handler=handler)
        with pytest.raises(FrozenInstanceError):
            definition.metadata = CommandMetadata(name="x", description="x")  # pyright: ignore[reportAttributeAccessIssue]

    def test_handler_is_callable(self) -> None:
        """Handler field が CommandHandler 形状の callable を保持することを検証する.

        Returns:
            None: handler field の callable 性を検証して完了する.
        """
        meta = CommandMetadata(name="test", description="test")

        async def test_handler(ctx: CommandContext) -> str | None:
            """Command 名を含む固定 response を返す test handler を提供する.

            Args:
                ctx (CommandContext): response へ command_name を提供する command context.

            Returns:
                str | None: command 名を含む handler response.
            """
            return f"{ctx.command_name} ran"

        definition = CommandDefinition(metadata=meta, handler=test_handler)
        assert callable(definition.handler)

    def test_handler_is_async(self) -> None:
        """Handler が async callable として await できることを検証する.

        Returns:
            None: event loop 上の handler response を検証して完了する.
        """
        meta = CommandMetadata(name="async", description="test")

        async def async_handler(_ctx: CommandContext) -> str | None:
            """Await 可能な固定 response handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: await 後に返す固定 response.
            """
            return "async result"

        _ = CommandDefinition(metadata=meta, handler=async_handler)

        result = asyncio.run(
            async_handler(
                CommandContext(
                    sender_id=1,
                    sender_name="u",
                    target="#o",
                    command_name="async",
                    args=(),
                    destination=CommandDestination.CHANNEL,
                    available_commands=(),
                )
            )
        )
        assert result == "async result"


class TestCommandRegistry:
    """CommandRegistry の登録と解決および一覧契約を検証する.

    command 名の正規化と metadata の registration order を対象とする.
    """

    @staticmethod
    def _make_definition(name: str, description: str = "") -> CommandDefinition:
        """指定 metadata を持つ最小 command definition を生成する.

        Args:
            name (str): registry へ登録する command 名.
            description (str): command metadata に設定する説明文.

        Returns:
            CommandDefinition: 値を返さない handler を持つ test 用 definition.
        """

        async def handler(_ctx: CommandContext) -> str | None:
            """値を返さずに完了する registry test 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        return CommandDefinition(
            metadata=CommandMetadata(name=name, description=description),
            handler=handler,
        )

    def test_register_and_resolve(self) -> None:
        """登録した definition を command 名で解決できることを検証する.

        Returns:
            None: resolve 結果が登録元 definition と同一であることを検証して完了する.
        """
        registry = CommandRegistry()
        definition = self._make_definition("roll", "Roll a number")
        registry.register(definition)

        resolved = registry.resolve("roll")
        assert resolved is definition

    def test_resolve_returns_none_for_unknown(self) -> None:
        """未登録の command 名を解決すると None になることを検証する.

        Returns:
            None: unknown command の resolve 結果を検証して完了する.
        """
        registry = CommandRegistry()
        assert registry.resolve("unknown") is None

    def test_resolve_is_case_insensitive(self) -> None:
        """Resolve が command 名の大文字小文字を区別しないことを検証する.

        Returns:
            None: 複数の表記が canonical definition を返すことを検証して完了する.
        """
        registry = CommandRegistry()
        definition = self._make_definition("roll", "Roll")
        registry.register(definition)

        assert registry.resolve("ROLL") is definition
        assert registry.resolve("Roll") is definition
        assert registry.resolve("rOLL") is definition

    def test_register_preserves_case(self) -> None:
        """登録後の command 名が小文字 canonical key として解決されることを検証する.

        registry 内部の key は小文字化されるが任意の大文字小文字表記で解決できる.

        Returns:
            None: 大文字表記と小文字表記が同じ definition を返すことを検証して完了する.
        """
        registry = CommandRegistry()
        definition = self._make_definition("roll")
        registry.register(definition)

        # Resolving by any case form returns the same definition
        assert registry.resolve("ROLL") is definition
        assert registry.resolve("roll") is definition

    def test_reject_duplicate_name(self) -> None:
        """同じ command 名の重複登録が拒否されることを検証する.

        Returns:
            None: 2 回目の登録が ValueError になることを検証して完了する.
        """
        registry = CommandRegistry()
        registry.register(self._make_definition("roll"))

        with pytest.raises(ValueError, match="roll"):
            registry.register(self._make_definition("roll"))

    def test_reject_duplicate_name_case_insensitive(self) -> None:
        """大文字小文字だけ異なる重複 command 名が拒否されることを検証する.

        Returns:
            None: canonical key の衝突が ValueError になることを検証して完了する.
        """
        registry = CommandRegistry()
        registry.register(self._make_definition("roll"))

        with pytest.raises(ValueError, match="roll"):
            registry.register(self._make_definition("ROLL"))

    def test_commands_empty_initially(self) -> None:
        """新規 registry の command list が空であることを検証する.

        Returns:
            None: 初期 commands 結果が空 tuple であることを検証して完了する.
        """
        registry = CommandRegistry()
        assert registry.commands() == ()

    def test_commands_lists_all(self) -> None:
        """Commands が全登録 metadata を registration order で返すことを検証する.

        Returns:
            None: 3 件の command 名と順序を検証して完了する.
        """
        registry = CommandRegistry()
        registry.register(self._make_definition("roll", "Roll"))
        registry.register(self._make_definition("help", "Help"))
        # Register a third command
        third_def = CommandDefinition(
            metadata=CommandMetadata(name="third", description="Third"),
            handler=lambda _: None,  # pyright: ignore[reportArgumentType]
        )
        registry.register(third_def)

        all_cmds = registry.commands()
        assert len(all_cmds) == 3
        assert all_cmds[0].name == "roll"
        assert all_cmds[1].name == "help"
        assert all_cmds[2].name == "third"

    def test_commands_preserves_registration_order(self) -> None:
        """Commands が registration order を維持することを検証する.

        Returns:
            None: help 用 metadata の挿入順を検証して完了する.
        """
        registry = CommandRegistry()
        registry.register(self._make_definition("help", "Help"))
        registry.register(self._make_definition("roll", "Roll"))
        registry.register(self._make_definition("stats", "Stats"))

        all_cmds = registry.commands()
        assert all_cmds[0].name == "help"
        assert all_cmds[1].name == "roll"
        assert all_cmds[2].name == "stats"

    def test_commands_returns_tuple(self) -> None:
        """Commands が immutable tuple を返すことを検証する.

        Returns:
            None: command list の container 型を検証して完了する.
        """
        registry = CommandRegistry()
        assert isinstance(registry.commands(), tuple)

    def test_registry_is_isolated(self) -> None:
        """Registry instance が global state を共有しないことを検証する.

        Returns:
            None: 一方の registry の登録が他方へ漏れないことを検証して完了する.
        """
        reg1 = CommandRegistry()
        reg2 = CommandRegistry()

        reg1.register(self._make_definition("roll"))
        assert reg1.resolve("roll") is not None
        assert reg2.resolve("roll") is None

    def test_reject_non_empty_name(self) -> None:
        """空の command 名の登録が拒否されることを検証する.

        Returns:
            None: 空名の registration が ValueError になることを検証して完了する.
        """
        registry = CommandRegistry()
        with pytest.raises(ValueError, match="empty"):
            registry.register(self._make_definition(""))

    def test_commands_includes_moderator_privileged_metadata(self) -> None:
        """MODERATOR command の metadata が commands から取得できることを検証する.

        Returns:
            None: name と required_privileges を検証して完了する.
        """
        registry = CommandRegistry()
        definition = CommandDefinition(
            metadata=CommandMetadata(
                name="modcmd",
                description="Moderator command",
                required_privileges=Privileges.MODERATOR,
            ),
            handler=lambda _: None,  # pyright: ignore[reportArgumentType]
        )
        registry.register(definition)

        all_cmds = registry.commands()
        assert len(all_cmds) == 1
        assert all_cmds[0].name == "modcmd"
        assert all_cmds[0].required_privileges == Privileges.MODERATOR

    def test_commands_includes_pm_destination_metadata(self) -> None:
        """PM 限定 command の destination metadata を取得できることを検証する.

        Returns:
            None: commands 結果の allowed_destinations を検証して完了する.
        """
        registry = CommandRegistry()
        definition = CommandDefinition(
            metadata=CommandMetadata(
                name="pmcmd",
                description="PM-only command",
                allowed_destinations=CommandDestination.PM,
            ),
            handler=lambda _: None,  # pyright: ignore[reportArgumentType]
        )
        registry.register(definition)

        all_cmds = registry.commands()
        assert len(all_cmds) == 1
        assert all_cmds[0].name == "pmcmd"
        assert all_cmds[0].allowed_destinations == CommandDestination.PM

    def test_commands_returns_all_regardless_of_privileges_or_destinations(self) -> None:
        """Commands が特権と送信先に関係なく全 command を返すことを検証する.

        Returns:
            None: public と privileged と destination 限定 command の全件を検証して完了する.
        """
        registry = CommandRegistry()
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(name="pub", description="Public"),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="mod",
                    description="Moderator",
                    required_privileges=Privileges.MODERATOR,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="admin",
                    description="Admin",
                    required_privileges=Privileges.ADMIN,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="pm_only",
                    description="PM only",
                    allowed_destinations=CommandDestination.PM,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )
        registry.register(
            CommandDefinition(
                metadata=CommandMetadata(
                    name="channel_only",
                    description="Channel only",
                    allowed_destinations=CommandDestination.CHANNEL,
                ),
                handler=lambda _: None,  # pyright: ignore[reportArgumentType]
            )
        )

        all_cmds = registry.commands()
        assert len(all_cmds) == 5
        names = [cmd.name for cmd in all_cmds]
        assert names == ["pub", "mod", "admin", "pm_only", "channel_only"]


class TestCommandDecorator:
    """Command decorator が生成する CommandDefinition を検証する.

    metadata と original handler が decorator 後も保持される契約を対象とする.
    """

    def test_decorator_returns_definition(self) -> None:
        """Command factory が handler から CommandDefinition を生成することを検証する.

        Returns:
            None: definition の metadata と既定特権を検証して完了する.
        """
        deco = command("roll", description="Roll a random number")

        async def roll_handler(_ctx: CommandContext) -> str | None:
            """固定の roll response を返す decorator test 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: decorator 後に期待する固定 response.
            """
            return "rolled"

        result = deco(roll_handler)
        assert isinstance(result, CommandDefinition)
        assert result.metadata.name == "roll"
        assert result.metadata.description == "Roll a random number"
        assert result.metadata.required_privileges == Privileges.NONE

    def test_decorator_handler_preserved(self) -> None:
        """Decorator が original handler の identity を保持することを検証する.

        Returns:
            None: definition.handler が元の callable と同一であることを検証して完了する.
        """
        deco = command("help", description="Help")

        async def help_handler(_ctx: CommandContext) -> str | None:
            """固定の help response を返す decorator test 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: decorator 後に期待する固定 response.
            """
            return "help text"

        definition = deco(help_handler)
        assert definition.handler is help_handler

    def test_decorator_registers_in_registry(self) -> None:
        """Decorator が生成した definition を registry へ登録できることを検証する.

        Returns:
            None: 登録後の resolve が同じ definition を返すことを検証して完了する.
        """
        registry = CommandRegistry()
        deco = command("roll", description="Roll a number")

        async def roll_handler(_ctx: CommandContext) -> str | None:
            """固定の roll response を返す registration test 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: registry 登録に使用する固定 response.
            """
            return "rolled"

        definition = deco(roll_handler)
        registry.register(definition)

        resolved = registry.resolve("roll")
        assert resolved is definition

    def test_registration_via_decorator_function(self) -> None:
        """Decorator factory による command 定義と登録を検証する.

        Returns:
            None: 定義済み metadata と callable handler を検証して完了する.
        """
        registry = CommandRegistry()

        deco = command("greet", description="Greet someone")

        async def greet_handler(ctx: CommandContext) -> str | None:
            """任意の最初の argument を挨拶に含める test handler を提供する.

            Args:
                ctx (CommandContext): 挨拶対象を args から取得する command context.

            Returns:
                str | None: argument の有無に応じた greeting response.
            """
            if ctx.args:
                return f"Hello, {ctx.args[0]}!"
            return "Hello!"

        definition = deco(greet_handler)
        registry.register(definition)

        resolved = registry.resolve("greet")
        assert resolved is not None
        assert resolved.metadata.description == "Greet someone"
        assert callable(resolved.handler)

    def test_visible_false(self) -> None:
        """Required_privileges を指定した decorator が privileged definition を作ることを検証する.

        Returns:
            None: metadata の ADMIN privilege を検証して完了する.
        """
        deco = command(
            "internal", description="Internal only", required_privileges=Privileges.ADMIN
        )

        async def internal_handler(_ctx: CommandContext) -> str | None:
            """Response を送信しない privileged command handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        definition = deco(internal_handler)
        assert definition.metadata.required_privileges == Privileges.ADMIN


class TestCommandDecoratorSyntax:
    """@command syntax による CommandDefinition 生成を検証する.

    decorator を直接付与した function の metadata と handler を対象とする.
    """

    def test_at_syntax_creates_definition(self) -> None:
        """@command syntax が CommandDefinition を生成することを検証する.

        Returns:
            None: definition の name と description と既定特権を検証して完了する.
        """

        @command("greet", description="Greet someone")
        async def greet(_ctx: CommandContext) -> str | None:
            """固定 greeting を返す decorator syntax 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: decorated definition が返す固定 greeting.
            """
            return "Hello!"

        assert isinstance(greet, CommandDefinition)
        assert greet.metadata.name == "greet"
        assert greet.metadata.description == "Greet someone"
        assert greet.metadata.required_privileges == Privileges.NONE

    def test_at_syntax_preserves_handler(self) -> None:
        """@command syntax が callable handler を保持することを検証する.

        Returns:
            None: decorated definition の handler callable 性を検証して完了する.
        """

        @command("echo", description="Echo input")
        async def echo(_ctx: CommandContext) -> str | None:
            """固定 echo response を返す decorator syntax 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: decorated definition が返す固定 echo response.
            """
            return "echo"

        assert callable(echo.handler)

    async def test_at_syntax_handler_invocable(self) -> None:
        """@command syntax で作る handler を呼び出せることを検証する.

        Returns:
            None: argument を含む handler response を検証して完了する.
        """

        @command("add", description="Add numbers")
        async def add(ctx: CommandContext) -> str | None:
            """最初の argument を sum response へ変換する handler を提供する.

            Args:
                ctx (CommandContext): sum に含める値を args から取得する command context.

            Returns:
                str | None: argument がある場合の sum response. 値がない場合はNone.
            """
            if ctx.args:
                return f"sum={ctx.args[0]}"
            return None

        ctx = CommandContext(
            sender_id=1,
            sender_name="u",
            target="#o",
            command_name="add",
            args=("42",),
            destination=CommandDestination.CHANNEL,
            available_commands=(),
        )
        result = await add.handler(ctx)
        assert result == "sum=42"

    def test_at_syntax_registers_in_registry(self) -> None:
        """@command syntax の definition を registry へ登録できることを検証する.

        Returns:
            None: resolve 結果が decorated definition と同一であることを検証して完了する.
        """

        @command("ping", description="Ping the bot")
        async def ping(_ctx: CommandContext) -> str | None:
            """固定 pong response を返す decorator syntax 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: decorated definition が返す固定 pong response.
            """
            return "pong"

        registry = CommandRegistry()
        registry.register(ping)

        resolved = registry.resolve("ping")
        assert resolved is not None
        assert resolved is ping
        assert resolved.metadata.name == "ping"

    def test_at_syntax_hidden_command(self) -> None:
        """@command syntax が required_privileges を metadata へ設定することを検証する.

        Returns:
            None: registered command の ADMIN privilege を検証して完了する.
        """

        @command("secret", description="Secret", required_privileges=Privileges.ADMIN)
        async def secret(_ctx: CommandContext) -> str | None:
            """Response を送信しない hidden command handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        registry = CommandRegistry()
        registry.register(secret)

        assert registry.commands()[0].required_privileges == Privileges.ADMIN


class TestRegistryCommandMethod:
    """CommandRegistry.command による自動登録を検証する.

    decorated handler の definition が registration order と metadata を保つ契約を対象とする.
    """

    def test_auto_registers_handler(self) -> None:
        """@registry.command が definition を自動登録することを検証する.

        Returns:
            None: resolve 結果と decorator が返す definition の identity を検証して完了する.
        """
        registry = CommandRegistry()

        @registry.command("greet", description="Greet someone")
        async def greet(_ctx: CommandContext) -> str | None:
            """固定 greeting を返す registry decorator 用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: registry に登録する固定 greeting response.
            """
            return "Hello!"

        resolved = registry.resolve("greet")
        assert resolved is not None
        assert resolved is greet
        assert resolved.metadata.name == "greet"

    def test_auto_registered_is_resolvable(self) -> None:
        """@registry.command 後に大文字小文字を問わず解決できることを検証する.

        Returns:
            None: canonical name と大文字表記の resolve 結果を検証して完了する.
        """
        registry = CommandRegistry()

        @registry.command("ping", description="Ping")
        async def ping(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """固定 pong response を返す自動登録用 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: registry に登録する固定 pong response.
            """
            return "pong"

        assert registry.resolve("ping") is not None
        assert registry.resolve("PING") is not None

    def test_auto_registered_appears_in_commands(self) -> None:
        """自動登録した command が commands 一覧へ現れることを検証する.

        Returns:
            None: 2 個の definition が登録順で一覧になることを検証して完了する.
        """
        registry = CommandRegistry()

        @registry.command("first", description="First")
        async def first(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない最初の自動登録 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        @registry.command("second", description="Second")
        async def second(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない 2 番目の自動登録 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        all_cmds = registry.commands()
        assert len(all_cmds) == 2
        assert all_cmds[0].name == "first"
        assert all_cmds[1].name == "second"

    def test_auto_register_hidden_command(self) -> None:
        """@registry.command が privileged command を自動登録することを検証する.

        Returns:
            None: resolve 結果と ADMIN privilege を検証して完了する.
        """
        registry = CommandRegistry()

        @registry.command("secret", description="Secret", required_privileges=Privileges.ADMIN)
        async def secret(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない privileged 自動登録 handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        assert registry.resolve("secret") is not None
        assert registry.commands()[0].required_privileges == Privileges.ADMIN

    def test_auto_register_preserves_insertion_order(self) -> None:
        """自動登録が decorator 呼び出し順を保持することを検証する.

        Returns:
            None: c と a と b の registration order を検証して完了する.
        """
        registry = CommandRegistry()

        @registry.command("c", description="C")
        async def c(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない c command handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        @registry.command("a", description="A")
        async def a(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない a command handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        @registry.command("b", description="B")
        async def b(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない b command handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        all_cmds = registry.commands()
        assert [cmd.name for cmd in all_cmds] == ["c", "a", "b"]

    def test_auto_register_pm_only_command(self) -> None:
        """@registry.command が PM 限定 command を自動登録することを検証する.

        Returns:
            None: resolve 結果と PM destination metadata を検証して完了する.
        """
        registry = CommandRegistry()

        @registry.command(
            "pmcmd", description="PM only", allowed_destinations=CommandDestination.PM
        )
        async def pmcmd(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない PM 限定 command handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        assert registry.resolve("pmcmd") is not None
        assert registry.commands()[0].allowed_destinations == CommandDestination.PM

    def test_auto_register_rejects_duplicate(self) -> None:
        """@registry.command による重複名の自動登録が拒否されることを検証する.

        Returns:
            None: 同名の 2 回目の decorator 適用が ValueError になることを検証して完了する.
        """
        registry = CommandRegistry()

        @registry.command("dup", description="First")
        async def first(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
            """Response を送信しない最初の duplicate test handler を提供する.

            Args:
                _ctx (CommandContext): handler contract を満たす未使用の command context.

            Returns:
                str | None: response を送信しないため None.
            """
            return None

        with pytest.raises(ValueError, match="dup"):

            @registry.command("dup", description="Second")
            async def second(_ctx: CommandContext) -> str | None:  # pyright: ignore[reportUnusedFunction]
                """Response を送信しない重複登録対象 handler を提供する.

                Args:
                    _ctx (CommandContext): handler contract を満たす未使用の command context.

                Returns:
                    str | None: response を送信しないため None.
                """
                return None
