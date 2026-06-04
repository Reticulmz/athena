"""Tests for the registry-backed CommandService.

Requirements covered:
- Req 1.1: !roll channel response
- Req 1.2: !roll PM response
- Req 1.3: !help response
- Req 1.4: unknown command response
- Req 1.5: non-command message ignored
- Req 2.1: case-insensitive command resolution
- Req 2.2: argument order preservation
- Req 2.3: prefix-only ignored
- Req 2.4: handler no-response returns None
- Req 3.2: CommandContext built from execute inputs
- Req 5.3: response target semantics unchanged
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

import pytest

from osu_server.domain.bancho_bot import CommandArgument, CommandDestination
from osu_server.domain.chat import ChatAuthorization, ChatCommandResponse
from osu_server.domain.role import Privileges
from osu_server.services.bancho_bot.command_service import CommandService
from osu_server.services.bancho_bot.commands.general import setup_general
from osu_server.services.bancho_bot.registry import CommandRegistry, command

if TYPE_CHECKING:
    from osu_server.domain.bancho_bot import CommandContext


@pytest.fixture
def registry() -> CommandRegistry:
    """Builtin registry with roll and help, matching the real builtin catalog."""
    reg = CommandRegistry()
    setup_general(reg)
    return reg


@pytest.fixture
def svc(registry: CommandRegistry) -> CommandService:
    return CommandService(registry)


def _response(target: str, content: str) -> ChatCommandResponse:
    return ChatCommandResponse(target=target, content=content)


# --- Req 1.5: non-command messages -------------------------------------------------


class TestNonCommandIgnored:
    """Req 1.5: messages without ! prefix return empty tuple."""

    async def test_plain_text_returns_empty(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "hello", authorization=ChatAuthorization())
        assert result == ()

    async def test_empty_content_returns_empty(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "", authorization=ChatAuthorization())
        assert result == ()


# --- Req 2.3: prefix-only content -------------------------------------------------


class TestPrefixOnlyIgnored:
    """Req 2.3: prefix-only or empty command name returns empty tuple."""

    async def test_bang_only_returns_empty(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!", authorization=ChatAuthorization())
        assert result == ()

    async def test_bang_with_spaces_returns_empty(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!   ", authorization=ChatAuthorization())
        assert result == ()


# --- Req 2.4: handler no-response -------------------------------------------------


class TestHandlerNoResponse:
    """Req 2.4: handler returning None yields empty tuple."""

    async def test_handler_returns_none(self) -> None:
        reg = CommandRegistry()

        async def _silent(_ctx: CommandContext) -> None:
            return None

        reg.register(command("silent", description="Silent")(_silent))
        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!silent", authorization=ChatAuthorization())
        assert result == ()


# --- Req 1.1: !roll channel response ---------------------------------------------


class TestRollChannel:
    """Req 1.1: !roll in channel returns response to channel."""

    async def test_roll_default_max(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(
                1, "Player", "#osu", "!roll", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 42 point(s)"),)

    async def test_roll_custom_max(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=23):
            result = await svc.execute(
                1, "Player", "#osu", "!roll 50", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 23 point(s)"),)


# --- Req 1.2: !roll PM response ---------------------------------------------------


class TestRollPM:
    """Req 1.2: !roll in PM returns response to sender."""

    async def test_roll_pm_target_is_sender(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=99):
            result = await svc.execute(
                1, "Player", "BanchoBot", "!roll", authorization=ChatAuthorization()
            )
        assert result == (_response("Player", "Player rolls 99 point(s)"),)


# --- Req 1.3: !help response -------------------------------------------------------


class TestHelpChannel:
    """Req 1.3: !help lists visible commands."""

    async def test_help_returns_available_commands(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)


# --- Req 1.4: unknown command ------------------------------------------------------


class TestUnknownCommand:
    """Req 1.4: unknown command returns standard message."""

    async def test_unknown_command_response(self, svc: CommandService) -> None:
        result = await svc.execute(
            1, "User", "#osu", "!unknown", authorization=ChatAuthorization()
        )
        assert result == (
            _response("#osu", "Unknown command. Type !help for available commands."),
        )

    async def test_unknown_command_pm_target(self, svc: CommandService) -> None:
        result = await svc.execute(
            1, "User", "BanchoBot", "!unknown", authorization=ChatAuthorization()
        )
        assert result == (
            _response("User", "Unknown command. Type !help for available commands."),
        )


# --- Req 2.1: case-insensitive resolution ------------------------------------------


class TestCaseInsensitiveResolution:
    """Req 2.1: command names resolve case-insensitively."""

    async def test_uppercase_roll(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(
                1, "Player", "#osu", "!ROLL", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 42 point(s)"),)

    async def test_mixed_case_help(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!Help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)


# --- Req 2.2: argument order preservation ------------------------------------------


class TestArgumentOrderPreservation:
    """Req 2.2: arguments preserve original order in CommandContext."""

    async def test_args_preserved_in_context(self) -> None:
        """Handler receives args in the order given by the player."""
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(
            1, "User", "#osu", "!capture first second 100 last", authorization=ChatAuthorization()
        )
        assert captured_args == [("first", "second", "100", "last")]

    async def test_single_arg(self) -> None:
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(1, "User", "#osu", "!capture 50", authorization=ChatAuthorization())
        assert captured_args == [("50",)]

    async def test_no_args(self) -> None:
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(1, "User", "#osu", "!capture", authorization=ChatAuthorization())
        assert captured_args == [()]


# --- Req 3.2, 5.3: response target semantics ---------------------------------------


class TestResponseTargetSemantics:
    """Req 5.3: channel target stays channel, PM target becomes sender name."""

    async def test_channel_target_preserved(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert len(result) == 1
        assert result[0].target == "#osu"

    async def test_pm_target_is_sender_name(self, svc: CommandService) -> None:
        result = await svc.execute(
            1, "User", "BanchoBot", "!help", authorization=ChatAuthorization()
        )
        assert len(result) == 1
        assert result[0].target == "User"

    async def test_channel_with_hash_prefix(self, svc: CommandService) -> None:
        """Any target starting with # is treated as channel."""
        result = await svc.execute(
            1, "User", "#multiplayer", "!help", authorization=ChatAuthorization()
        )
        assert len(result) == 1
        assert result[0].target == "#multiplayer"

    async def test_pm_without_hash_prefix(self, svc: CommandService) -> None:
        """Any target not starting with # is treated as PM."""
        result = await svc.execute(1, "Alice", "Bob", "!help", authorization=ChatAuthorization())
        assert len(result) == 1
        assert result[0].target == "Alice"


# --- Req 3.2: CommandContext built from execute inputs -----------------------------


class TestCommandContextBuiltCorrectly:
    """Req 3.2: CommandContext carries sender identity, destination, command name, args."""

    async def test_context_sender_identity(self) -> None:
        reg = CommandRegistry()
        captured: list[CommandContext] = []

        async def _capture(ctx: CommandContext) -> str:
            captured.append(ctx)
            return "ok"

        reg.register(command("who", description="who")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(42, "PlayerOne", "#osu", "!who", authorization=ChatAuthorization())
        assert len(captured) == 1
        assert captured[0].sender_id == 42
        assert captured[0].sender_name == "PlayerOne"

    async def test_context_includes_available_commands(self) -> None:
        """CommandContext.available_commands matches registry commands."""
        reg = CommandRegistry()
        captured: list[CommandContext] = []

        async def _capture(ctx: CommandContext) -> str:
            captured.append(ctx)
            return "ok"

        reg.register(command("who", description="who")(_capture))
        svc2 = CommandService(reg)

        _ = await svc2.execute(1, "User", "#osu", "!who", authorization=ChatAuthorization())
        assert len(captured) == 1
        assert captured[0].available_commands == reg.commands()


# --- Edge cases --------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge case coverage."""

    async def test_extra_whitespace_between_args(self, svc: CommandService) -> None:
        """Extra whitespace between args is collapsed by split()."""
        with mock.patch("random.randint", return_value=50):
            result = await svc.execute(
                1, "Player", "#osu", "!roll   50   ", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 50 point(s)"),)

    async def test_leading_whitespace_prevents_match(self, svc: CommandService) -> None:
        """Content that starts with whitespace is not a command."""
        result = await svc.execute(1, "User", "#osu", "  !help", authorization=ChatAuthorization())
        assert result == ()

    async def test_bang_in_middle_is_not_a_command(self, svc: CommandService) -> None:
        result = await svc.execute(
            1, "User", "#osu", "hello !world", authorization=ChatAuthorization()
        )
        assert result == ()


# --- Privilege authorization tests -----------------------------------------------


class TestPrivilegeAuthorization:
    """Privilege-based entry authorization (Req 1.2, 1.3, 1.4, 1.5, 1.7, 2.3, 2.5, 2.8)."""

    UNKNOWN_RESPONSE: str = "Unknown command. Type !help for available commands."

    async def test_public_command_executes_without_privileges(self) -> None:
        """!roll with no privileges works -- public commands require none."""
        reg = CommandRegistry()
        setup_general(reg)
        svc = CommandService(reg)

        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(
                1, "Player", "#osu", "!roll", authorization=ChatAuthorization()
            )
        assert result == (_response("#osu", "Player rolls 42 point(s)"),)

    async def test_privileged_command_requires_privileges(self) -> None:
        """MODERATOR command, no privileges -> unknown response."""
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "done"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!modonly", authorization=ChatAuthorization()
        )
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)

    async def test_privileged_command_executes_with_required_privileges(self) -> None:
        """MODERATOR command, MODERATOR user -> executes."""
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!modonly", authorization=auth)
        assert result == (_response("#osu", "done"),)

    async def test_admin_bypasses_all_privileges(self) -> None:
        """MODERATOR command, ADMIN user -> executes (bypass)."""
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.ADMIN)
        result = await svc.execute(1, "Admin", "#osu", "!modonly", authorization=auth)
        assert result == (_response("#osu", "done"),)

    async def test_multi_privilege_requires_all(self) -> None:
        """Command requiring MODERATOR|DEVELOPER, user with only MODERATOR -> unknown."""
        reg = CommandRegistry()

        @reg.command(
            "special",
            description="Special",
            usage="!special",
            required_privileges=Privileges.MODERATOR | Privileges.DEVELOPER,
        )
        async def _special(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "ok"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!special", authorization=auth)
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)

    async def test_unauthorized_same_response_as_unknown(self) -> None:
        """Unauthorized and unregistered command both return identical unknown message."""
        reg = CommandRegistry()

        @reg.command(
            "adminonly",
            description="Admin only",
            usage="!adminonly",
            required_privileges=Privileges.ADMIN,
        )
        async def _adminonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "secret"

        svc = CommandService(reg)

        unknown = await svc.execute(1, "User", "#osu", "!bogus", authorization=ChatAuthorization())
        unauthorized = await svc.execute(
            1, "User", "#osu", "!adminonly", authorization=ChatAuthorization()
        )
        assert unknown == unauthorized

    async def test_privilege_check_ignores_role_ids(self) -> None:
        """MODERATOR command, role_ids don't matter -- only privileges count."""
        reg = CommandRegistry()

        @reg.command(
            "modonly",
            description="Mod only",
            usage="!modonly",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "done"

        svc = CommandService(reg)

        # role_ids present but no MODERATOR privilege -> rejected
        auth = ChatAuthorization(privileges=Privileges.NONE, role_ids=(1, 2, 3))
        result = await svc.execute(1, "User", "#osu", "!modonly", authorization=auth)
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)


# --- Destination gating ----------------------------------------------------------


class TestDestinationGating:
    """Destination gating (Req 2.1, 2.2, 2.3, 2.6, 2.7, 2.8)."""

    UNKNOWN_RESPONSE: str = "Unknown command. Type !help for available commands."

    @staticmethod
    def _make_pm_only_registry() -> CommandRegistry:
        reg = CommandRegistry()

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "pm result"

        return reg

    @staticmethod
    def _make_channel_only_registry() -> CommandRegistry:
        reg = CommandRegistry()

        @reg.command(
            "chcmd",
            description="Channel only",
            usage="!chcmd",
            allowed_destinations=CommandDestination.CHANNEL,
        )
        async def _chcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "channel result"

        return reg

    async def test_pm_only_executes_in_pm(self) -> None:
        """PM-only command in PM executes normally."""
        reg = self._make_pm_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!pmcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "pm result"),)

    async def test_pm_only_in_channel_returns_unknown_and_guidance(self) -> None:
        """PM-only command in channel: channel unknown + sender PM guidance."""
        reg = self._make_pm_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!pmcmd", authorization=ChatAuthorization())
        assert result == (
            _response("#osu", self.UNKNOWN_RESPONSE),
            _response("User", "The !pmcmd command can only be used in pm."),
        )

    async def test_channel_only_executes_in_channel(self) -> None:
        """Channel-only command in channel executes normally."""
        reg = self._make_channel_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!chcmd", authorization=ChatAuthorization())
        assert result == (_response("#osu", "channel result"),)

    async def test_channel_only_in_pm_returns_guidance(self) -> None:
        """Channel-only command in PM: sender PM guidance only."""
        reg = self._make_channel_only_registry()
        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!chcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "The !chcmd command can only be used in channel."),)

    async def test_pm_only_in_channel_unauthorized_no_guidance(self) -> None:
        """PM-only + privileged command in channel by unauthorized user: unknown only."""
        reg = CommandRegistry()

        @reg.command(
            "secretpm",
            description="Secret PM",
            usage="!secretpm",
            required_privileges=Privileges.MODERATOR,
            allowed_destinations=CommandDestination.PM,
        )
        async def _secretpm(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "secret"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!secretpm", authorization=ChatAuthorization()
        )
        # Unauthorized → unknown only, no guidance (Req 2.8)
        assert result == (_response("#osu", self.UNKNOWN_RESPONSE),)

    async def test_both_destination_works_in_channel(self) -> None:
        """BOTH destination command works in channel."""
        reg = CommandRegistry()

        @reg.command("bothcmd", description="Both", usage="!bothcmd")
        async def _bothcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "both ok"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!bothcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("#osu", "both ok"),)

    async def test_both_destination_works_in_pm(self) -> None:
        """BOTH destination command works in PM."""
        reg = CommandRegistry()

        @reg.command("bothcmd", description="Both", usage="!bothcmd")
        async def _bothcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "both ok"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!bothcmd", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "both ok"),)


# --- Help visibility filtering -------------------------------------------------


class TestHelpVisibilityFiltering:
    """Help lists only commands executable in current destination (Req 3.1-3.4, 3.7)."""

    async def test_channel_help_excludes_pm_only_commands(self) -> None:
        """PM-only command not visible in channel !help, even for privileged users."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "pm result"

        svc = CommandService(reg)

        # Channel help should only show channel-available commands
        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)

    async def test_pm_help_includes_pm_only_commands(self) -> None:
        """PM-only command visible in PM !help."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "pm result"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "BanchoBot", "!help", authorization=ChatAuthorization()
        )
        assert result == (_response("User", "Available commands: !roll, !help, !pmcmd"),)

    async def test_help_excludes_privileged_commands_for_unauthorized(self) -> None:
        """Privileged command not visible in !help for unprivileged users."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "mod done"

        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help"),)

    async def test_help_includes_privileged_commands_for_authorized(self) -> None:
        """Privileged command visible in !help for authorized users."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "mod done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!help", authorization=auth)
        assert result == (_response("#osu", "Available commands: !roll, !help, !modcmd"),)

    async def test_help_preserves_registration_order(self) -> None:
        """!help lists commands in registry order after filtering."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command("c", description="C", usage="!c")
        async def _c(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "c"

        @reg.command("a", description="A", usage="!a")
        async def _a(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "a"

        @reg.command("b", description="B", usage="!b")
        async def _b(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "b"

        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!help", authorization=ChatAuthorization())
        assert result == (_response("#osu", "Available commands: !roll, !help, !c, !a, !b"),)

    async def test_admin_sees_all_destination_compatible_commands(self) -> None:
        """ADMIN sees all destination-compatible commands in channel help."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "mod done"

        @reg.command(
            "admincmd",
            description="Admin command",
            usage="!admincmd",
            required_privileges=Privileges.ADMIN,
            allowed_destinations=CommandDestination.CHANNEL,
        )
        async def _admincmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "admin done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.ADMIN)
        result = await svc.execute(1, "Admin", "#osu", "!help", authorization=auth)
        assert result == (
            _response("#osu", "Available commands: !roll, !help, !modcmd, !admincmd"),
        )

    async def test_channel_help_excludes_pm_only_even_for_admin(self) -> None:
        """PM-only commands are excluded from channel help even for ADMIN (Req 3.7)."""
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
            return "secret"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.ADMIN)
        result = await svc.execute(1, "Admin", "#osu", "!help", authorization=auth)
        # secretpm should NOT appear in channel help
        assert result == (_response("#osu", "Available commands: !roll, !help"),)


# --- Common help options -------------------------------------------------------


class TestCommonHelpOptions:
    """Common --help and !help --all behavior (Req 3.5, 3.6, 4.1, 4.2, 4.4, 4.5, 4.6)."""

    async def test_help_help_returns_meta_help(self, svc: CommandService) -> None:
        """!help --help returns usage and options for !help itself (Req 3.6)."""
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
        """!<command> --help shows name, usage, arguments (Req 4.1)."""
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
        """Detail help for command with no arguments shows only usage."""
        reg = CommandRegistry()

        @reg.command("simple", description="Simple", usage="!simple")
        async def _simple(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "ok"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!simple --help", authorization=ChatAuthorization()
        )
        assert result == (_response("#osu", "Usage: !simple"),)

    async def test_detail_help_with_multiple_arguments(self) -> None:
        """Detail help lists all arguments with required/optional status."""
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
        """Unauthorized !<command> --help returns unknown (Req 4.2)."""
        reg = CommandRegistry()

        @reg.command(
            "adminonly",
            description="Admin only",
            usage="!adminonly",
            required_privileges=Privileges.ADMIN,
        )
        async def _adminonly(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "secret"

        svc = CommandService(reg)

        result = await svc.execute(
            1, "User", "#osu", "!adminonly --help", authorization=ChatAuthorization()
        )
        assert result == (
            _response("#osu", "Unknown command. Type !help for available commands."),
        )

    async def test_help_as_non_first_arg_goes_to_handler(self) -> None:
        """--help not as first arg is passed to handler as normal arg (Req 4.6)."""
        reg = CommandRegistry()
        captured: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
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
        """Detail help never shows required_privileges (Req 4.4)."""
        reg = CommandRegistry()

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
            return "mod done"

        svc = CommandService(reg)

        auth = ChatAuthorization(privileges=Privileges.MODERATOR)
        result = await svc.execute(1, "Mod", "#osu", "!modcmd --help", authorization=auth)
        content = result[0].content
        assert "MODERATOR" not in content
        assert "privilege" not in content.lower()

    async def test_help_all_shows_names_and_descriptions(self) -> None:
        """!help --all lists command names and descriptions (Req 3.5)."""
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
        """!help --all excludes PM-only commands in channel (Req 3.3, 3.7)."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "pmcmd",
            description="PM only",
            usage="!pmcmd",
            allowed_destinations=CommandDestination.PM,
        )
        async def _pmcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
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
        """!help --all excludes privileged commands for unauthorized users (Req 3.2)."""
        reg = CommandRegistry()
        setup_general(reg)

        @reg.command(
            "modcmd",
            description="Mod command",
            usage="!modcmd",
            required_privileges=Privileges.MODERATOR,
        )
        async def _modcmd(_ctx: CommandContext) -> str:  # pyright: ignore[reportUnusedFunction]
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
