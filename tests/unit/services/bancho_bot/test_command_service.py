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

from osu_server.domain.chat import ChatCommandResponse
from osu_server.services.bancho_bot.command_service import CommandService
from osu_server.services.bancho_bot.commands.general import setup_general
from osu_server.services.bancho_bot.registry import CommandRegistry, command

if TYPE_CHECKING:
    from osu_server.services.bancho_bot.context import CommandContext


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
    """Req 1.5: messages without ! prefix return None."""

    async def test_plain_text_returns_none(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "hello")
        assert result is None

    async def test_empty_content_returns_none(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "")
        assert result is None


# --- Req 2.3: prefix-only content -------------------------------------------------


class TestPrefixOnlyIgnored:
    """Req 2.3: prefix-only or empty command name returns None."""

    async def test_bang_only_returns_none(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!")
        assert result is None

    async def test_bang_with_spaces_returns_none(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!   ")
        assert result is None


# --- Req 2.4: handler no-response -------------------------------------------------


class TestHandlerNoResponse:
    """Req 2.4: handler returning None yields no command response."""

    async def test_handler_returns_none(self) -> None:
        reg = CommandRegistry()

        async def _silent(_ctx: CommandContext) -> None:
            return None

        reg.register(command("silent", description="Silent")(_silent))
        svc = CommandService(reg)

        result = await svc.execute(1, "User", "#osu", "!silent")
        assert result is None


# --- Req 1.1: !roll channel response ---------------------------------------------


class TestRollChannel:
    """Req 1.1: !roll in channel returns response to channel."""

    async def test_roll_default_max(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(1, "Player", "#osu", "!roll")
        assert result == _response("#osu", "Player rolls 42 point(s)")

    async def test_roll_custom_max(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=23):
            result = await svc.execute(1, "Player", "#osu", "!roll 50")
        assert result == _response("#osu", "Player rolls 23 point(s)")


# --- Req 1.2: !roll PM response ---------------------------------------------------


class TestRollPM:
    """Req 1.2: !roll in PM returns response to sender."""

    async def test_roll_pm_target_is_sender(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=99):
            result = await svc.execute(1, "Player", "BanchoBot", "!roll")
        assert result == _response("Player", "Player rolls 99 point(s)")


# --- Req 1.3: !help response -------------------------------------------------------


class TestHelpChannel:
    """Req 1.3: !help lists visible commands."""

    async def test_help_returns_available_commands(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!help")
        assert result == _response("#osu", "Available commands: !roll, !help")


# --- Req 1.4: unknown command ------------------------------------------------------


class TestUnknownCommand:
    """Req 1.4: unknown command returns standard message."""

    async def test_unknown_command_response(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!unknown")
        assert result == _response("#osu", "Unknown command. Type !help for available commands.")

    async def test_unknown_command_pm_target(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "BanchoBot", "!unknown")
        assert result == _response("User", "Unknown command. Type !help for available commands.")


# --- Req 2.1: case-insensitive resolution ------------------------------------------


class TestCaseInsensitiveResolution:
    """Req 2.1: command names resolve case-insensitively."""

    async def test_uppercase_roll(self, svc: CommandService) -> None:
        with mock.patch("random.randint", return_value=42):
            result = await svc.execute(1, "Player", "#osu", "!ROLL")
        assert result == _response("#osu", "Player rolls 42 point(s)")

    async def test_mixed_case_help(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!Help")
        assert result == _response("#osu", "Available commands: !roll, !help")


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

        _ = await svc.execute(1, "User", "#osu", "!capture first second 100 last")
        assert captured_args == [("first", "second", "100", "last")]

    async def test_single_arg(self) -> None:
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(1, "User", "#osu", "!capture 50")
        assert captured_args == [("50",)]

    async def test_no_args(self) -> None:
        reg = CommandRegistry()
        captured_args: list[tuple[str, ...]] = []

        async def _capture(ctx: CommandContext) -> str:
            captured_args.append(ctx.args)
            return "ok"

        reg.register(command("capture", description="capture")(_capture))
        svc = CommandService(reg)

        _ = await svc.execute(1, "User", "#osu", "!capture")
        assert captured_args == [()]


# --- Req 3.2, 5.3: response target semantics ---------------------------------------


class TestResponseTargetSemantics:
    """Req 5.3: channel target stays channel, PM target becomes sender name."""

    async def test_channel_target_preserved(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "!help")
        assert result is not None
        assert result.target == "#osu"

    async def test_pm_target_is_sender_name(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "BanchoBot", "!help")
        assert result is not None
        assert result.target == "User"

    async def test_channel_with_hash_prefix(self, svc: CommandService) -> None:
        """Any target starting with # is treated as channel."""
        result = await svc.execute(1, "User", "#multiplayer", "!help")
        assert result is not None
        assert result.target == "#multiplayer"

    async def test_pm_without_hash_prefix(self, svc: CommandService) -> None:
        """Any target not starting with # is treated as PM."""
        result = await svc.execute(1, "Alice", "Bob", "!help")
        assert result is not None
        assert result.target == "Alice"


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

        _ = await svc.execute(42, "PlayerOne", "#osu", "!who")
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

        _ = await svc2.execute(1, "User", "#osu", "!who")
        assert len(captured) == 1
        assert captured[0].available_commands == reg.commands()


# --- Edge cases --------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge case coverage."""

    async def test_extra_whitespace_between_args(self, svc: CommandService) -> None:
        """Extra whitespace between args is collapsed by split()."""
        with mock.patch("random.randint", return_value=50):
            result = await svc.execute(1, "Player", "#osu", "!roll   50   ")
        assert result == _response("#osu", "Player rolls 50 point(s)")

    async def test_leading_whitespace_prevents_match(self, svc: CommandService) -> None:
        """Content that starts with whitespace is not a command."""
        result = await svc.execute(1, "User", "#osu", "  !help")
        assert result is None

    async def test_bang_in_middle_is_not_a_command(self, svc: CommandService) -> None:
        result = await svc.execute(1, "User", "#osu", "hello !world")
        assert result is None
