import random
from collections.abc import Awaitable, Callable
from typing import ClassVar

from osu_server.domain.system_user import BANCHO_BOT_IDENTITY

CommandHandler = Callable[[int, str, list[str]], Awaitable[str | None]]


class CommandService:
    BANCHO_BOT_ID: ClassVar[int] = BANCHO_BOT_IDENTITY.user_id
    BANCHO_BOT_NAME: ClassVar[str] = BANCHO_BOT_IDENTITY.username

    def __init__(self) -> None:
        self._commands: dict[str, CommandHandler] = {}
        self._register_defaults()

    def register(self, name: str, handler: CommandHandler) -> None:
        self._commands[name] = handler

    def _register_defaults(self) -> None:
        self.register("roll", self._cmd_roll)
        self.register("help", self._cmd_help)

    async def _cmd_roll(self, _sender_id: int, sender_name: str, args: list[str]) -> str | None:
        max_val = 100
        if args and args[0].isdigit():
            max_val = int(args[0])
            max_val = max(max_val, 1)

        result = random.randint(0, max_val)
        return f"{sender_name} rolls {result} point(s)"

    async def _cmd_help(self, _sender_id: int, _sender_name: str, _args: list[str]) -> str | None:
        available = ", ".join(f"!{cmd}" for cmd in self._commands)
        return f"Available commands: {available}"

    async def execute(
        self, sender_id: int, sender_name: str, target: str, content: str
    ) -> tuple[str, str] | None:
        if not content.startswith("!"):
            return None

        parts = content[1:].strip().split()
        if not parts:
            return None

        cmd_name = parts[0].lower()
        args = parts[1:]

        response_target = target
        if not target.startswith("#"):
            # When BanchoBot replies in PM, the target is the user who sent the command.
            response_target = sender_name

        handler = self._commands.get(cmd_name)
        if handler:
            response = await handler(sender_id, sender_name, args)
        else:
            response = "Unknown command. Type !help for available commands."

        if response:
            return response_target, response
        return None
