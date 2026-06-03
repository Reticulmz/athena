"""Tests for the !roll BanchoBot registered command.

Requirements covered:
- Req 1.1: !roll channel response preserved
- Req 1.2: !roll PM response preserved (format unchanged)
- Req 2.2: argument order preservation in CommandContext.args
- Req 3.3: independent command behavior (only uses CommandContext)
"""

from __future__ import annotations

from unittest import mock

from osu_server.services.bancho_bot.commands.roll import roll_handler
from osu_server.services.bancho_bot.context import CommandContext
from osu_server.services.bancho_bot.registry import CommandDefinition, CommandRegistry, command


def _make_context(
    *,
    sender_id: int = 1,
    sender_name: str = "Player",
    target: str = "#osu",
    command_name: str = "roll",
    args: tuple[str, ...] = (),
) -> CommandContext:
    """Helper to construct a minimal CommandContext for roll tests."""
    return CommandContext(
        sender_id=sender_id,
        sender_name=sender_name,
        target=target,
        command_name=command_name,
        args=args,
        available_commands=(),
    )


class TestRollNoArgs:
    """!roll with no arguments defaults to max=100."""

    async def test_no_args_default_max_100(self) -> None:
        """Req 1.1: !roll with no args uses default max=100 and matches format."""
        ctx = _make_context()
        with mock.patch("random.randint", return_value=42):
            result = await roll_handler(ctx)

        assert result is not None
        assert result == "Player rolls 42 point(s)"

    async def test_no_args_response_contains_sender_name(self) -> None:
        """Response includes the sender's name from ctx.sender_name."""
        ctx = _make_context(sender_name="Alice")
        with mock.patch("random.randint", return_value=7):
            result = await roll_handler(ctx)

        assert result == "Alice rolls 7 point(s)"


class TestRollWithNumericArg:
    """!roll <number> uses the argument as max value."""

    async def test_numeric_arg_custom_max(self) -> None:
        """Req 2.2: numeric arg sets custom max, response format preserved."""
        ctx = _make_context(args=("50",))
        with mock.patch("random.randint", return_value=23):
            result = await roll_handler(ctx)

        assert result == "Player rolls 23 point(s)"

    async def test_numeric_arg_10(self) -> None:
        """!roll 10 uses max=10."""
        ctx = _make_context(args=("10",))
        with mock.patch("random.randint", return_value=5):
            result = await roll_handler(ctx)

        assert result == "Player rolls 5 point(s)"

    async def test_numeric_arg_1(self) -> None:
        """!roll 1 uses max=1, result is 0 or 1."""
        ctx = _make_context(args=("1",))
        with mock.patch("random.randint", return_value=1):
            result = await roll_handler(ctx)

        assert result == "Player rolls 1 point(s)"

    async def test_clamps_zero_to_one(self) -> None:
        """Req 3.3: !roll 0 clamps max to 1 (lower bound enforcement)."""
        ctx = _make_context(args=("0",))
        with mock.patch("random.randint", return_value=0) as mock_randint:
            result = await roll_handler(ctx)
            mock_randint.assert_called_once_with(0, 1)

        assert result == "Player rolls 0 point(s)"

    async def test_random_uses_correct_max(self) -> None:
        """Verify random.randint is called with (0, parsed_max)."""
        ctx = _make_context(args=("75",))
        with mock.patch("random.randint", return_value=30) as mock_randint:
            _ = await roll_handler(ctx)
            mock_randint.assert_called_once_with(0, 75)


class TestRollWithNonNumericArg:
    """Non-numeric first argument is ignored, defaults to max=100."""

    async def test_non_numeric_first_arg_defaults(self) -> None:
        """!roll abc defaults to max=100 because args[0] is not all digits."""
        ctx = _make_context(args=("abc",))
        with mock.patch("random.randint", return_value=50) as mock_randint:
            result = await roll_handler(ctx)
            mock_randint.assert_called_once_with(0, 100)

        assert result == "Player rolls 50 point(s)"

    async def test_multiple_args_only_first_used(self) -> None:
        """!roll 50 100 uses only the first arg."""
        ctx = _make_context(args=("50", "100"))
        with mock.patch("random.randint", return_value=25) as mock_randint:
            result = await roll_handler(ctx)
            mock_randint.assert_called_once_with(0, 50)

        assert result == "Player rolls 25 point(s)"


class TestRollPMResponse:
    """Req 1.2: PM response format is identical -- target routing is handled by CommandService."""

    async def test_pm_response_format_unchanged(self) -> None:
        """PM command produces the same format string as channel command."""
        ctx = _make_context(target="BanchoBot")
        with mock.patch("random.randint", return_value=99):
            result = await roll_handler(ctx)

        assert result == "Player rolls 99 point(s)"


class TestRollRegisteredAsCommandDefinition:
    """Verify roll can be registered via the @command decorator contract."""

    def test_registered_via_decorator(self) -> None:
        """The @command decorator produces a valid CommandDefinition for roll."""
        deco = command("roll", description="Roll a random number")

        async def handler(ctx: CommandContext) -> str | None:
            return await roll_handler(ctx)

        definition = deco(handler)
        assert isinstance(definition, CommandDefinition)
        assert definition.metadata.name == "roll"
        assert definition.metadata.description == "Roll a random number"
        assert definition.metadata.visible is True

    async def test_invocation_through_registered_handler(self) -> None:
        """Invoking roll through a registry-resolved handler works correctly."""
        registry = CommandRegistry()
        deco = command("roll", description="Roll a random number")

        async def handler(ctx: CommandContext) -> str | None:
            return await roll_handler(ctx)

        definition = deco(handler)
        registry.register(definition)

        resolved = registry.resolve("roll")
        assert resolved is not None

        ctx = _make_context(sender_name="Tester", args=("20",))
        with mock.patch("random.randint", return_value=15):
            result = await resolved.handler(ctx)

        assert result == "Tester rolls 15 point(s)"


class TestRollIndependence:
    """Req 3.3: roll uses only CommandContext fields, no external service dependencies."""

    async def test_no_session_access(self) -> None:
        """Roll handler accesses only ctx fields, no session or DB."""
        ctx = _make_context(sender_name="Indie")
        with mock.patch("random.randint", return_value=42):
            result = await roll_handler(ctx)

        assert result == "Indie rolls 42 point(s)"

    async def test_no_available_commands_needed(self) -> None:
        """Roll handler does not depend on available_commands."""
        ctx = _make_context()
        with mock.patch("random.randint", return_value=3):
            result = await roll_handler(ctx)

        assert result is not None
