"""registry-backed CommandServiceのcommand解決とresponse contractを検証するtest module.

!roll, !help, 未知command, destination判定, authorization判定が既存のobservable
responseを維持することを検証する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

import pytest

from osu_server.domain.chat import ChatAuthorization, ChatCommandResponse
from osu_server.domain.chat.commands import CommandArgument, CommandDestination
from osu_server.domain.identity.authorization import Privileges
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.chat.bancho_bot.commands.general import setup_general
from osu_server.services.commands.chat.bancho_bot.registry import CommandRegistry, command

if TYPE_CHECKING:
    from osu_server.domain.chat.commands import CommandContext


@pytest.fixture
def registry() -> CommandRegistry:
    """Builtin rollとhelp commandを持つregistry fixtureを提供する.

    Returns:
        CommandRegistry: 実際のbuiltin catalogと同じcommandを登録したregistry.
    """
    reg = CommandRegistry()
    setup_general(reg)
    return reg


@pytest.fixture
def svc(registry: CommandRegistry) -> CommandService:
    """Builtin registryを使うCommandService fixtureを提供する.

    Args:
        registry (CommandRegistry): builtin commandを登録済みのregistry fixture.

    Returns:
        CommandService: command実行contractを検証するservice.
    """
    return CommandService(registry)


def _response(target: str, content: str) -> ChatCommandResponse:
    """期待値比較用のchat command responseを組み立てる.

    Args:
        target (str): responseを送るchannelまたはuser名.
        content (str): responseに含めるtext.

    Returns:
        ChatCommandResponse: 指定targetとcontentを持つ期待response.
    """
    return ChatCommandResponse(target=target, content=content)


# --- Req 1.5: non-command messages -------------------------------------------------


class TestNonCommandIgnored:
    """! prefixを持たないmessageを無視するcontractを検証するtest群."""

    async def test_plain_text_returns_empty(self, svc: CommandService) -> None:
        """通常textがresponseなしの空tupleへ解決されることを検証する.

        Args:
            svc (CommandService): plain textを実行するservice fixture.

        Returns:
            None: responseが生成されないことを検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "hello", authorization=ChatAuthorization())
        assert result == ()

    async def test_empty_content_returns_empty(self, svc: CommandService) -> None:
        """空contentがresponseなしの空tupleへ解決されることを検証する.

        Args:
            svc (CommandService): 空contentを実行するservice fixture.

        Returns:
            None: responseが生成されないことを検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "", authorization=ChatAuthorization())
        assert result == ()


# --- Req 2.3: prefix-only content -------------------------------------------------


class TestPrefixOnlyIgnored:
    """command名を持たない! prefixを無視するcontractを検証するtest群."""

    async def test_bang_only_returns_empty(self, svc: CommandService) -> None:
        """!だけのcontentが空tupleへ解決されることを検証する.

        Args:
            svc (CommandService): prefix-only contentを実行するservice fixture.

        Returns:
            None: responseが生成されないことを検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "!", authorization=ChatAuthorization())
        assert result == ()

    async def test_bang_with_spaces_returns_empty(self, svc: CommandService) -> None:
        """空白だけが続く! prefixが空tupleへ解決されることを検証する.

        Args:
            svc (CommandService): 空白付きprefix-only contentを実行するservice fixture.

        Returns:
            None: responseが生成されないことを検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "!   ", authorization=ChatAuthorization())
        assert result == ()


# --- Req 2.4: handler no-response -------------------------------------------------


class TestHandlerNoResponse:
    """responseを返さないhandlerが空tupleへ解決されるcontractを検証するtest群."""

    async def test_handler_returns_none(self) -> None:
        """None responseのhandlerがresponseを生成しないことを検証する.

        Returns:
            None: empty response tupleを検証して完了する.
        """
        reg = CommandRegistry()

        async def _silent(_ctx: CommandContext) -> None:
            """responseを返さず終了するtest用command handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                None: responseを返さずに完了する.
            """
            return

        reg.register(command("silent", description="Silent")(_silent))
        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!silent", authorization=ChatAuthorization())
        assert result == ()


# --- Req 1.1: !roll channel response ---------------------------------------------


class TestRollChannel:
    """channel内!rollのresponse targetとvalueを検証するtest群."""

    async def test_roll_default_max(self, svc: CommandService) -> None:
        """既定上限の!rollがchannelへ乱数responseを返すことを検証する.

        Args:
            svc (CommandService): builtin !rollを実行するservice fixture.

        Returns:
            None: channel targetと既定乱数responseを検証して完了する.
        """
        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(
                1, "Player", "#osu", "!roll", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 42 point(s)"),)

    async def test_roll_custom_max(self, svc: CommandService) -> None:
        """明示上限の!rollがchannelへ指定範囲のresponseを返すことを検証する.

        Args:
            svc (CommandService): 引数付き!rollを実行するservice fixture.

        Returns:
            None: channel targetと乱数responseを検証して完了する.
        """
        with mock.patch("random.randint", return_value=23):
            result = await svc.execute(
                1, "Player", "#osu", "!roll 50", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 23 point(s)"),)


# --- Req 1.2: !roll PM response ---------------------------------------------------


class TestRollPM:
    """PM内!rollのresponseが送信者へ向くcontractを検証するtest群."""

    async def test_roll_pm_target_is_sender(self, svc: CommandService) -> None:
        """PMの!roll response targetがBanchoBotではなく送信者になることを検証する.

        Args:
            svc (CommandService): PM内!rollを実行するservice fixture.

        Returns:
            None: 送信者targetの乱数responseを検証して完了する.
        """
        with mock.patch("random.randint", return_value=99):
            result = await svc.execute(
                1, "Player", "BanchoBot", "!roll", authorization=ChatAuthorization()
            )
        assert result == (_response("Player", "Player rolls 99 point(s)"),)


# --- Req 1.3: !help response -------------------------------------------------------


class TestHelpChannel:
    """channel内!helpが可視commandを列挙するcontractを検証するtest群."""

    async def test_help_returns_available_commands(self, svc: CommandService) -> None:
        """!helpがbuiltin command一覧をchannelへ返すことを検証する.

        Args:
            svc (CommandService): builtin !helpを実行するservice fixture.

        Returns:
            None: visible commandのresponseを検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)


# --- Req 1.4: unknown command ------------------------------------------------------


class TestUnknownCommand:
    """未登録commandがstandard unknown responseを返すcontractを検証するtest群."""

    async def test_unknown_command_response(self, svc: CommandService) -> None:
        """channel内の未登録commandがunknown messageを返すことを検証する.

        Args:
            svc (CommandService): 未登録commandを実行するservice fixture.

        Returns:
            None: channelへ返るunknown responseを検証して完了する.
        """
        result = await svc.execute(
            1, "User", "#osu", "!unknown", authorization=ChatAuthorization()
        )
        assert result == (
            _response("#osu", "Unknown command. Type !help for available commands."),
        )

    async def test_unknown_command_pm_target(self, svc: CommandService) -> None:
        """PM内の未登録commandが送信者へunknown messageを返すことを検証する.

        Args:
            svc (CommandService): PM内の未登録commandを実行するservice fixture.

        Returns:
            None: 送信者targetのunknown responseを検証して完了する.
        """
        result = await svc.execute(
            1, "User", "BanchoBot", "!unknown", authorization=ChatAuthorization()
        )
        assert result == (
            _response("User", "Unknown command. Type !help for available commands."),
        )


# --- Req 2.1: case-insensitive resolution ------------------------------------------


class TestCaseInsensitiveResolution:
    """command名をcase-insensitiveに解決するcontractを検証するtest群."""

    async def test_uppercase_roll(self, svc: CommandService) -> None:
        """大文字!ROLLがbuiltin !rollと同じresponseを返すことを検証する.

        Args:
            svc (CommandService): 大文字commandを実行するservice fixture.

        Returns:
            None: case-insensitiveな!roll解決を検証して完了する.
        """
        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(
                1, "Player", "#osu", "!ROLL", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 42 point(s)"),)

    async def test_mixed_case_help(self, svc: CommandService) -> None:
        """mixed-case !Helpがbuiltin !helpと同じresponseを返すことを検証する.

        Args:
            svc (CommandService): mixed-case commandを実行するservice fixture.

        Returns:
            None: case-insensitiveな!help解決を検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "!Help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)


# --- Req 2.2: argument order preservation ------------------------------------------


class TestArgumentOrderPreservation:
    """CommandContextへ渡すargument順を維持するcontractを検証するtest群."""

    async def test_args_preserved_in_context(self) -> None:
        """複数argumentが入力順のままhandlerへ渡ることを検証する.

        Returns:
            None: 捕捉したargument tupleの順序を検証して完了する.
        """
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            """argument順を捕捉して固定responseを返すtest用handler.

            Args:
                ctx (CommandContext): 捕捉対象のcommand実行context.

            Returns:
                str: serviceがresponseへ変換する固定content.
            """
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(
            1, "User", "#osu", "!capture first second 100 last", authorization=ChatAuthorization()
        )
        assert captured_args == [("first", "second", "100", "last")]

    async def test_single_arg(self) -> None:
        """1個のargumentが1要素tupleとしてhandlerへ渡ることを検証する.

        Returns:
            None: 捕捉した1要素tupleを検証して完了する.
        """
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            """Single argumentを捕捉して固定responseを返すtest用handler.

            Args:
                ctx (CommandContext): 捕捉対象のcommand実行context.

            Returns:
                str: serviceがresponseへ変換する固定content.
            """
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(1, "User", "#osu", "!capture 50", authorization=ChatAuthorization())
        assert captured_args == [("50",)]

    async def test_no_args(self) -> None:
        """argumentなしcommandが空tupleをhandlerへ渡すことを検証する.

        Returns:
            None: 捕捉した空argument tupleを検証して完了する.
        """
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            """argumentなしcontextを捕捉して固定responseを返すtest用handler.

            Args:
                ctx (CommandContext): 捕捉対象のcommand実行context.

            Returns:
                str: serviceがresponseへ変換する固定content.
            """
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(1, "User", "#osu", "!capture", authorization=ChatAuthorization())
        assert captured_args == [()]


# --- Req 3.2, 5.3: response target semantics ---------------------------------------


class TestResponseTargetSemantics:
    """channelとPMで異なるresponse target contractを検証するtest群."""

    async def test_channel_target_preserved(self, svc: CommandService) -> None:
        """channel宛て!helpのtargetがchannel名のままになることを検証する.

        Args:
            svc (CommandService): channel内!helpを実行するservice fixture.

        Returns:
            None: response targetがchannel名であることを検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert len(result) == 1
        assert result[0].target == "#osu"

    async def test_pm_target_is_sender_name(self, svc: CommandService) -> None:
        """PM宛て!helpのtargetが送信者名になることを検証する.

        Args:
            svc (CommandService): PM内!helpを実行するservice fixture.

        Returns:
            None: response targetが送信者名であることを検証して完了する.
        """
        result = await svc.execute(
            1, "User", "BanchoBot", "!help", authorization=ChatAuthorization()
        )
        assert len(result) == 1
        assert result[0].target == "User"

    async def test_channel_with_hash_prefix(self, svc: CommandService) -> None:
        """#で始まる任意targetがchannelとして扱われることを検証する.

        Args:
            svc (CommandService): multiplayer channel内!helpを実行するservice fixture.

        Returns:
            None: targetがchannel名のまま保たれることを検証して完了する.
        """
        result = await svc.execute(
            1, "User", "#multiplayer", "!help", authorization=ChatAuthorization()
        )
        assert len(result) == 1
        assert result[0].target == "#multiplayer"

    async def test_pm_without_hash_prefix(self, svc: CommandService) -> None:
        """#で始まらない任意targetがPMとして扱われることを検証する.

        Args:
            svc (CommandService): user名宛て!helpを実行するservice fixture.

        Returns:
            None: response targetが送信者名になることを検証して完了する.
        """
        result = await svc.execute(1, "Alice", "Bob", "!help", authorization=ChatAuthorization())
        assert len(result) == 1
        assert result[0].target == "Alice"


# --- Req 3.2: CommandContext built from execute inputs -----------------------------


class TestCommandContextBuiltCorrectly:
    """execute inputからCommandContextを組み立てるcontractを検証するtest群."""

    async def test_context_sender_identity(self) -> None:
        """Sender IDとnameがhandlerのCommandContextへ渡ることを検証する.

        Returns:
            None: 捕捉したsender identityを検証して完了する.
        """
        reg = CommandRegistry()
        captured: list[CommandContext] = []

        async def _capture(ctx: CommandContext) -> str:
            """CommandContextを捕捉して固定responseを返すtest用handler.

            Args:
                ctx (CommandContext): sender identityを含む実行context.

            Returns:
                str: serviceがresponseへ変換する固定content.
            """
            captured.append(ctx)
            return "ok"

        reg.register(command("who", description="who")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(42, "PlayerOne", "#osu", "!who", authorization=ChatAuthorization())
        assert len(captured) == 1
        assert captured[0].sender_id == 42
        assert captured[0].sender_name == "PlayerOne"

    async def test_context_includes_available_commands(self) -> None:
        """available_commandsがregistryの登録順commandと一致することを検証する.

        Returns:
            None: 捕捉したavailable command一覧を検証して完了する.
        """
        reg = CommandRegistry()
        captured: list[CommandContext] = []

        async def _capture(ctx: CommandContext) -> str:
            """Available commandを含むcontextを捕捉するtest用handler.

            Args:
                ctx (CommandContext): registry由来のcommand一覧を含む実行context.

            Returns:
                str: serviceがresponseへ変換する固定content.
            """
            captured.append(ctx)
            return "ok"

        reg.register(command("who", description="who")(_capture))
        svc2 = CommandService(reg)

        _ = await svc2.execute(1, "User", "#osu", "!who", authorization=ChatAuthorization())
        assert len(captured) == 1
        assert captured[0].available_commands == reg.commands()


# --- Edge cases --------------------------------------------------------------------


class TestEdgeCases:
    """command parserの境界入力を検証するtest群."""

    async def test_extra_whitespace_between_args(self, svc: CommandService) -> None:
        """argument間の余分な空白がsplit()で正規化されることを検証する.

        Args:
            svc (CommandService): 空白を含む!rollを実行するservice fixture.

        Returns:
            None: 正規化後の!roll responseを検証して完了する.
        """
        with mock.patch("random.randint", return_value=50):
            result = await svc.execute(
                1, "Player", "#osu", "!roll   50   ", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 50 point(s)"),)

    async def test_leading_whitespace_prevents_match(self, svc: CommandService) -> None:
        """先頭空白付きcontentがcommandとして扱われないことを検証する.

        Args:
            svc (CommandService): 先頭空白付きcontentを実行するservice fixture.

        Returns:
            None: responseが生成されないことを検証して完了する.
        """
        result = await svc.execute(1, "User", "#osu", "  !help", authorization=ChatAuthorization())
        assert result == ()

    async def test_bang_in_middle_is_not_a_command(self, svc: CommandService) -> None:
        """文中の!がcommand prefixとして扱われないことを検証する.

        Args:
            svc (CommandService): 文中に!を含むcontentを実行するservice fixture.

        Returns:
            None: responseが生成されないことを検証して完了する.
        """
        result = await svc.execute(
            1, "User", "#osu", "hello !world", authorization=ChatAuthorization()
        )
        assert result == ()


# --- Privilege authorization tests -----------------------------------------------


class TestPrivilegeAuthorization:
    """privilegeに基づくcommand実行authorization contractを検証するtest群.

    Attributes:
        UNKNOWN_RESPONSE (str): 未許可commandにも返すunknown command response.
    """

    UNKNOWN_RESPONSE: str = "Unknown command. Type !help for available commands."

    async def test_public_command_executes_without_privileges(self) -> None:
        """Public !rollがprivilegeなしでも実行できることを検証する.

        Returns:
            None: public commandのresponseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)
        svc = CommandService(reg)

        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(
                1, "Player", "#osu", "!roll", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 42 point(s)"),)

    async def test_privileged_command_requires_privileges(self) -> None:
        """MODERATOR commandがprivilegeなしではunknown responseになることを検証する.

        Returns:
            None: 未許可commandのunknown responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR権限が必要な固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時にserviceがresponseへ変換するcontent.
            """
            return "done"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!modonly", authorization=ChatAuthorization()
        )
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)

    async def test_privileged_command_executes_with_required_privileges(self) -> None:
        """MODERATOR commandが同権限を持つuserには実行されることを検証する.

        Returns:
            None: 許可後のcommand responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR権限が必要な固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時にserviceがresponseへ変換するcontent.
            """
            return "done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!modonly", authorization=auth)
        assert result == (_response("#osu", "done"),)

    async def test_admin_bypasses_all_privileges(self) -> None:
        """ADMINがMODERATOR requirementをbypassして実行できることを検証する.

        Returns:
            None: administratorのcommand responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR権限が必要な固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時にserviceがresponseへ変換するcontent.
            """
            return "done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.ADMIN)
        result = await svc.execute(1, "Admin", "#osu", "!modonly", authorization=auth)
        assert result == (_response("#osu", "done"),)

    async def test_multi_privilege_requires_all(self) -> None:
        """複数privilege requirementがすべて必要なことを検証する.

        Returns:
            None: 一部のprivilegeだけではunknown responseになることを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "special",
            description="Special",
            usage="!special",
            required_privileges=Privileges.MODERATOR | Privileges.DEVELOPER,
        )
        async def _special(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """複数privilegeを必要とする固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 全権限を満たす場合に返すcontent.
            """
            return "ok"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!special", authorization=auth)
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)

    async def test_unauthorized_same_response_as_unknown(self) -> None:
        """未許可commandと未登録commandが同じunknown responseを返すことを検証する.

        Returns:
            None: authorization状態を漏らさない等しいresponseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "adminonly",
            description="Admin only",
            usage="!adminonly",
            required_privileges=Privileges.ADMIN,
        )
        async def _adminonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """ADMIN権限が必要な固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時に返すsecret content.
            """
            return "secret"

        svc = CommandService(reg)

        unknown = await svc.execute(1, "User", "#osu", "!bogus", authorization=ChatAuthorization())
        unauthorized = await svc.execute(
            1, "User", "#osu", "!adminonly", authorization=ChatAuthorization()
        )
        assert unknown == unauthorized

    async def test_privilege_check_ignores_role_ids(self) -> None:
        """Role IDではなくprivilegeだけでcommand許可を判定することを検証する.

        Returns:
            None: MODERATOR privilege不在のunknown responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR権限が必要な固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時にserviceがresponseへ変換するcontent.
            """
            return "done"

        svc = CommandService(reg)

        # role_ids present but no MODERATOR privilege -> rejected
        auth = ChatAuthorization(privileges=Privileges.NONE, role_ids=(1, 2, 3))
        result = await svc.execute(1, "User", "#osu", "!modonly", authorization=auth)
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)


# --- Destination gating ----------------------------------------------------------


class TestDestinationGating:
    """command destination制約とguidance responseを検証するtest群.

    Attributes:
        UNKNOWN_RESPONSE (str): destination判定前の未許可commandにも返すresponse.
    """

    UNKNOWN_RESPONSE: str = "Unknown command. Type !help for available commands."

    @staticmethod
    def _make_pm_only_registry() -> CommandRegistry:
        """PM専用commandを登録したtest用registryを組み立てる.

        Returns:
            CommandRegistry: PM destinationだけを許可するpmcmdを持つregistry.
        """
        reg = CommandRegistry()

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """PM専用固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: PMで許可されたときに返すcontent.
            """
            return "pm result"

        return reg

    @staticmethod
    def _make_channel_only_registry() -> CommandRegistry:
        """channel専用commandを登録したtest用registryを組み立てる.

        Returns:
            CommandRegistry: channel destinationだけを許可するchcmdを持つregistry.
        """
        reg = CommandRegistry()

        @reg.command(
            "chcmd",
            description="Channel only",
            usage="!chcmd",
            allowed_destinations=CommandDestination.CHANNEL,
        )
        async def _chcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """channel専用固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: channelで許可されたときに返すcontent.
            """
            return "channel result"

        return reg

    async def test_pm_only_executes_in_pm(self) -> None:
        """PM専用commandがPM内では通常どおり実行されることを検証する.

        Returns:
            None: 送信者targetのPM command responseを検証して完了する.
        """
        reg = self._make_pm_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!pmcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "pm result"),)

    async def test_pm_only_in_channel_returns_unknown_and_guidance(self) -> None:
        """PM専用commandがchannel内ではunknown responseとPM guidanceを返すことを検証する.

        Returns:
            None: channel responseと送信者向けguidanceの順序を検証して完了する.
        """
        reg = self._make_pm_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!pmcmd", authorization=ChatAuthorization())
        assert result == (
            _response("#osu", self.UNKNOWN_RESPONSE),
            _response("User", "The !pmcmd command can only be used in pm."),
        )

    async def test_channel_only_executes_in_channel(self) -> None:
        """channel専用commandがchannel内では通常どおり実行されることを検証する.

        Returns:
            None: channel targetのcommand responseを検証して完了する.
        """
        reg = self._make_channel_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!chcmd", authorization=ChatAuthorization())
        assert result == (_response("#osu", "channel result"),)

    async def test_channel_only_in_pm_returns_guidance(self) -> None:
        """channel専用commandがPM内では送信者向けguidanceだけを返すことを検証する.

        Returns:
            None: PM guidance responseだけが返ることを検証して完了する.
        """
        reg = self._make_channel_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!chcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "The !chcmd command can only be used in channel."),)

    async def test_pm_only_in_channel_unauthorized_no_guidance(self) -> None:
        """未許可PM専用commandがguidanceなしのunknown responseになることを検証する.

        Returns:
            None: authorizationを漏らさない単一responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "secretpm",
            description="Secret PM",
            usage="!secretpm",
            required_privileges=Privileges.MODERATOR,
            allowed_destinations=CommandDestination.PM,
        )
        async def _secretpm(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR向けPM専用固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可済みPMで返すsecret content.
            """
            return "secret"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!secretpm", authorization=ChatAuthorization()
        )
        # Unauthorized → unknown only, no guidance (Req 2.8)
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)

    async def test_both_destination_works_in_channel(self) -> None:
        """destination未制限commandがchannel内で実行されることを検証する.

        Returns:
            None: channel targetのresponseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command("bothcmd", description="Both", usage="!bothcmd")
        async def _bothcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """両destinationで使える固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時に返すcontent.
            """
            return "both ok"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!bothcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("#osu", "both ok"),)

    async def test_both_destination_works_in_pm(self) -> None:
        """destination未制限commandがPM内で実行されることを検証する.

        Returns:
            None: 送信者targetのresponseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command("bothcmd", description="Both", usage="!bothcmd")
        async def _bothcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """両destinationで使える固定responseのtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時に返すcontent.
            """
            return "both ok"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!bothcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "both ok"),)


# --- Help visibility filtering -------------------------------------------------


class TestHelpVisibilityFiltering:
    """!helpがdestinationとprivilegeで可視commandをfilterするcontractを検証するtest群."""

    async def test_channel_help_excludes_pm_only_commands(self) -> None:
        """channel内!helpがPM専用commandを除外することを検証する.

        Returns:
            None: PM専用commandを含まないhelp responseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """PM専用固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: PMで許可されたときに返すcontent.
            """
            return "pm result"

        svc = CommandService(reg)

        # Channel help should only show channel-available commands
        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)

    async def test_pm_help_includes_pm_only_commands(self) -> None:
        """PM内!helpがPM専用commandを表示することを検証する.

        Returns:
            None: PM専用commandを含むhelp responseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """PM専用固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: PMで許可されたときに返すcontent.
            """
            return "pm result"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!help", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "Available commands: !roll, !help, !pmcmd"),)

    async def test_help_excludes_privileged_commands_for_unauthorized(self) -> None:
        """privilegeなしuserの!helpがprivileged commandを除外することを検証する.

        Returns:
            None: privileged commandを含まないhelp responseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR向け固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: MODERATOR userへ返すcontent.
            """
            return "mod done"

        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)

    async def test_help_includes_privileged_commands_for_authorized(self) -> None:
        """必要privilegeを持つuserの!helpがcommandを表示することを検証する.

        Returns:
            None: privileged commandを含むhelp responseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR向け固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: MODERATOR userへ返すcontent.
            """
            return "mod done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!help", authorization=auth)
        assert result == (_response("#osu", "Available commands: !roll, !help, !modcmd"),)

    async def test_help_preserves_registration_order(self) -> None:
        """!helpがfilter後もregistry登録順を保つことを検証する.

        Returns:
            None: custom commandの登録順を持つhelp responseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command("c", description="C", usage="!c")
        async def _c(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """登録順確認用のC command responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: C commandの固定content.
            """
            return "c"

        @reg.command("a", description="A", usage="!a")
        async def _a(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """登録順確認用のA command responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: A commandの固定content.
            """
            return "a"

        @reg.command("b", description="B", usage="!b")
        async def _b(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """登録順確認用のB command responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: B commandの固定content.
            """
            return "b"

        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help, !c, !a, !b"),)

    async def test_admin_sees_all_destination_compatible_commands(self) -> None:
        """ADMINのchannel !helpがcompatibleなprivileged commandをすべて表示することを検証する.

        Returns:
            None: destination互換なMODERATOR/ADMIN commandを含むresponseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR向け固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: MODERATOR userへ返すcontent.
            """
            return "mod done"

        @reg.command(
            "admincmd",
            description="Admin command",
            usage="!admincmd",
            required_privileges=Privileges.ADMIN,
            allowed_destinations=CommandDestination.CHANNEL,
        )
        async def _admincmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """ADMIN向け固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: ADMIN userへ返すcontent.
            """
            return "admin done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.ADMIN)
        result = await svc.execute(1, "Admin", "#osu", "!help", authorization=auth)
        assert result == (
            _response("#osu", "Available commands: !roll, !help, !modcmd, !admincmd"),
        )

    async def test_channel_help_excludes_pm_only_even_for_admin(self) -> None:
        """ADMINのchannel !helpもPM専用commandを除外することを検証する.

        Returns:
            None: PM専用commandを含まないhelp responseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "secretpm",
            description="Secret PM",
            usage="!secretpm",
            required_privileges=Privileges.ADMIN,
            allowed_destinations=CommandDestination.PM,
        )
        async def _secretpm(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """ADMIN向けPM専用responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可済みPMで返すsecret content.
            """
            return "secret"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.ADMIN)
        result = await svc.execute(1, "Admin", "#osu", "!help", authorization=auth)
        # secretpm should NOT appear in channel help
        assert result == (_response("#osu", "Available commands: !roll, !help"),)


# --- Common help options -------------------------------------------------------


class TestCommonHelpOptions:
    """!help optionとcommand詳細helpの表示contractを検証するtest群."""

    async def test_help_help_returns_meta_help(self, svc: CommandService) -> None:
        """!help --helpが!help自身のusageとoptionを返すことを検証する.

        Args:
            svc (CommandService): builtin !helpを実行するservice fixture.

        Returns:
            None: !helpのmeta help responseを検証して完了する.
        """
        result = await svc.execute(
            1, "User", "#osu", "!help --help", authorization=ChatAuthorization()
        )
        assert result == (
            _response(
                "#osu",
                (
                    "Usage: !help [--all]\n"
                    "Options:\n"
                    "  --all  Show all available commands with descriptions"
                ),
            ),
        )

    async def test_detail_help_shows_usage_and_arguments(self) -> None:
        """Command --helpがusageとrequired argumentを表示することを検証する.

        Returns:
            None: command詳細helpのusageとargument説明を検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "greet",
            description="Greet someone",
            usage="!greet <name>",
            arguments=(
                CommandArgument(name="name", required=True, description="The name to greet"),
            ),
        )
        async def _greet(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """詳細help確認用のgreet responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: greet commandの固定content.
            """
            return "hello"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!greet --help", authorization=ChatAuthorization()
        )
        assert result == (
            _response(
                "#osu",
                "Usage: !greet <name>\nArguments:\n  name (required) - The name to greet",
            ),
        )

    async def test_detail_help_without_arguments(self) -> None:
        """argumentなしcommandの詳細helpがusageだけを表示することを検証する.

        Returns:
            None: argument sectionを持たないusage responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command("simple", description="Simple", usage="!simple")
        async def _simple(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """argumentなし詳細help確認用の固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: simple commandの固定content.
            """
            return "ok"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!simple --help", authorization=ChatAuthorization()
        )
        assert result == (_response("#osu", "Usage: !simple"),)

    async def test_detail_help_with_multiple_arguments(self) -> None:
        """詳細helpがrequired/optionalを含む全argumentを表示することを検証する.

        Returns:
            None: 複数argumentの詳細help responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "cmd",
            description="Test",
            usage="!cmd <req> [opt]",
            arguments=(
                CommandArgument(name="req", required=True, description="Required arg"),
                CommandArgument(name="opt", required=False, description="Optional arg"),
            ),
        )
        async def _cmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """複数argumentの詳細help確認用固定responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: cmd commandの固定content.
            """
            return "ok"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!cmd --help", authorization=ChatAuthorization()
        )
        expected = (
            "Usage: !cmd <req> [opt]\n"
            "Arguments:\n"
            "  req (required) - Required arg\n"
            "  opt (optional) - Optional arg"
        )
        assert result == (_response("#osu", expected),)

    async def test_unauthorized_detail_help_returns_unknown(self) -> None:
        """未許可commandの詳細helpがunknown responseになることを検証する.

        Returns:
            None: authorization状態を漏らさないunknown responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "adminonly",
            description="Admin only",
            usage="!adminonly",
            required_privileges=Privileges.ADMIN,
        )
        async def _adminonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """ADMIN向け詳細help確認用responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: 許可時に返すsecret content.
            """
            return "secret"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!adminonly --help", authorization=ChatAuthorization()
        )
        assert result == (
            _response("#osu", "Unknown command. Type !help for available commands."),
        )

    async def test_help_as_non_first_arg_goes_to_handler(self) -> None:
        """先頭以外の--helpが通常argumentとしてhandlerへ渡ることを検証する.

        Returns:
            None: handlerが受け取るargument tupleを検証して完了する.
        """
        reg = CommandRegistry()
        captured: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            """通常argumentを捕捉して固定responseを返すtest用handler.

            Args:
                ctx (CommandContext): 捕捉対象のcommand実行context.

            Returns:
                str: serviceがresponseへ変換する固定content.
            """
            captured.append(ctx.args)
            return "ok"

        reg.register(command("test", description="Test", usage="!test")(_capture))
        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!test arg1 --help", authorization=ChatAuthorization()
        )
        assert result == (_response("#osu", "ok"),)
        assert captured == [("arg1", "--help")]

    async def test_detail_help_does_not_show_privileges(self) -> None:
        """詳細helpがrequired_privilegesを表示しないことを検証する.

        Returns:
            None: privilege名を含まない詳細help responseを検証して完了する.
        """
        reg = CommandRegistry()

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR向け詳細help確認用responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: MODERATOR userへ返すcontent.
            """
            return "mod done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!modcmd --help", authorization=auth)
        content = result[0].content
        assert "MODERATOR" not in content
        assert "privilege" not in content.lower()

    async def test_help_all_shows_names_and_descriptions(self) -> None:
        """!help --allがcommand nameとdescriptionを表示することを検証する.

        Returns:
            None: builtin commandのnameとdescriptionを持つresponseを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!help --all", authorization=ChatAuthorization()
        )
        expected = (
            "Available commands:\n"
            "  !roll - Roll a random number\n"
            "  !help - Show available commands"
        )
        assert result == (_response("#osu", expected),)

    async def test_help_all_respects_destination_filtering(self) -> None:
        """!help --allがdestinationに応じてPM専用commandをfilterすることを検証する.

        Returns:
            None: channelでは除外しPMでは表示することを検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """PM専用help filter確認用responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: PMで許可されたときに返すcontent.
            """
            return "pm"

        svc = CommandService(reg)

        # Channel: pmcmd excluded
        result_ch = await svc.execute(
            1, "User", "#osu", "!help --all", authorization=ChatAuthorization()
        )
        assert "!pmcmd" not in result_ch[0].content

        # PM: pmcmd included
        result_pm = await svc.execute(
            1, "User", "BanchoBot", "!help --all", authorization=ChatAuthorization()
        )
        assert "!pmcmd - PM only" in result_pm[0].content

    async def test_help_all_respects_privilege_filtering(self) -> None:
        """!help --allがprivilegeなしuserからprivileged commandをfilterすることを検証する.

        Returns:
            None: 未許可時の除外と許可時の表示を検証して完了する.
        """
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            """MODERATOR向けhelp filter確認用responseを返すtest用handler.

            Args:
                _ctx (CommandContext): registryが渡すcommand実行context.

            Returns:
                str: MODERATOR userへ返すcontent.
            """
            return "mod"

        svc = CommandService(reg)

        # Unauthorized: modcmd excluded
        result = await svc.execute(
            1, "User", "#osu", "!help --all", authorization=ChatAuthorization()
        )
        assert "!modcmd" not in result[0].content

        # Authorized: modcmd included
        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result_mod = await svc.execute(1, "Mod", "#osu", "!help --all", authorization=auth)
        assert "!modcmd - Mod command" in result_mod[0].content
