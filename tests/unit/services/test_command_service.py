import random

import pytest

from osu_server.services.command_service import CommandService


@pytest.fixture
def command_service() -> CommandService:
    return CommandService()


@pytest.mark.asyncio
async def test_execute_roll_command(
    command_service: CommandService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monkeypatch random.randint to always return a specific value for predictability.
    def mock_randint(_a: int, b: int) -> int:
        return b

    monkeypatch.setattr(random, "randint", mock_randint)

    # test !roll with default
    result = await command_service.execute(
        sender_id=100, sender_name="User", target="#osu", content="!roll"
    )
    assert result is not None
    assert result[0] == "#osu"
    assert result[1] == "User rolls 100 point(s)"

    # test !roll with custom max
    result_50 = await command_service.execute(
        sender_id=100, sender_name="User", target="#osu", content="!roll 50"
    )
    assert result_50 is not None
    assert result_50[0] == "#osu"
    assert result_50[1] == "User rolls 50 point(s)"


@pytest.mark.asyncio
async def test_execute_help_command(command_service: CommandService) -> None:
    result = await command_service.execute(
        sender_id=100, sender_name="User", target="#osu", content="!help"
    )
    assert result is not None
    assert result[0] == "#osu"
    assert result[1] == "Available commands: !roll, !help"


@pytest.mark.asyncio
async def test_execute_unknown_command(command_service: CommandService) -> None:
    result = await command_service.execute(
        sender_id=100, sender_name="User", target="#osu", content="!unknown"
    )
    assert result is not None
    assert result[0] == "#osu"
    assert result[1] == "Unknown command. Type !help for available commands."


@pytest.mark.asyncio
async def test_execute_command_in_pm(command_service: CommandService) -> None:
    # If the command is sent in a PM (target is BanchoBot or user's name),
    # the response should be sent to the sender's PM.
    # In Bancho, PMs target the recipient's username.
    # If target does not start with '#', response target is sender_name.

    result = await command_service.execute(
        sender_id=100, sender_name="User", target="BanchoBot", content="!help"
    )
    assert result is not None
    assert result[0] == "User"
    assert result[1] == "Available commands: !roll, !help"
