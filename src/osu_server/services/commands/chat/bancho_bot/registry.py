"""BanchoBot command の registry と decorator contract を提供する.

この module は command metadata と async handler の immutable binding
を定義し、case-insensitive な
lookup と決定的な登録順を提供する. builtin catalog と plugin-like command setup は同じ
decorator
contract を利用できる.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from osu_server.domain.chat.commands import (
    CommandArgument,
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.domain.identity.authorization import Privileges

CommandHandler = Callable[[CommandContext], Awaitable[str | None]]


@dataclass(slots=True, frozen=True)
class CommandDefinition:
    """command metadata と async handler の immutable binding を表す.

    `@command` decorator で生成でき、`CommandRegistry` へ登録して command service から解決する.

    Attributes:
        metadata (CommandMetadata): name、usage、visibility を含む command metadata.
        handler (CommandHandler):
            `CommandContext` を受けて optional response text を返す async handler.
    """

    metadata: CommandMetadata
    handler: CommandHandler


class CommandRegistry:
    """型付き command definition を保存、解決、一覧化する registry.

    command は canonical lowercase name で保存し、metadata の一覧では登録順を保持する.
    duplicate name は
    registration 時に拒否し、instance ごとに独立した mutable state を持つ.

    Attributes:
        _definitions (dict[str, CommandDefinition]):
            canonical lowercase name から definition への lookup table.
        _insertion_order (list[str]):
            `commands()` の決定的な順序を保持する canonical name の列.
    """

    def __init__(self) -> None:
        """空の command registry を初期化する."""
        self._definitions: dict[str, CommandDefinition] = {}
        self._insertion_order: list[str] = []

    def register(self, definition: CommandDefinition) -> None:
        """Command definition を canonical name で登録する.

        Args:
            definition (CommandDefinition): 登録する metadata と async handler の binding.

        Returns:
            None: definition を lookup table と登録順へ追加し、呼び出し側へ値を返さない.

        Raises:
            ValueError: command name が空、または case-insensitive にすでに登録済みの場合.
        """
        name = definition.metadata.name
        canonical = name.lower()

        if not canonical:
            raise ValueError("Command name must not be empty")

        if canonical in self._definitions:
            raise ValueError(f"Command '{canonical}' is already registered")

        self._definitions[canonical] = definition
        self._insertion_order.append(canonical)

    def resolve(self, name: str) -> CommandDefinition | None:
        """Command name を case-insensitive に解決する.

        Args:
            name (str): 任意の case で指定する command name.

        Returns:
            CommandDefinition | None: 登録済み definition. 見つからない場合はNone.
        """
        return self._definitions.get(name.lower())

    def commands(self) -> tuple[CommandMetadata, ...]:
        """全 command metadata を登録順で返す.

        Returns:
            tuple[CommandMetadata, ...]: visibility filter 前の全 command metadata を保持する
            immutable
            tuple.
        """
        return tuple(self._definitions[name].metadata for name in self._insertion_order)

    def command(
        self,
        name: str,
        *,
        description: str,
        usage: str = "",
        arguments: tuple[CommandArgument, ...] = (),
        required_privileges: Privileges = Privileges.NONE,
        allowed_destinations: CommandDestination = CommandDestination.BOTH,
    ) -> Callable[[CommandHandler], CommandDefinition]:
        """Handler を CommandDefinition へ変換してこの registry に登録する decorator を返す.

        Args:
            name (str): canonical command name. lowercase を推奨する.
            description (str): help output に表示する人間向け説明.
            usage (str): `!roll [max]`のような help 用 usage text. 既定値は空文字列.
            arguments (tuple[CommandArgument, ...]):
                受け付ける argument の metadata. 既定値は空 tuple.
            required_privileges (Privileges):
                command 実行に必要な server-side privilege. 既定値は`Privileges.NONE`.
            allowed_destinations (CommandDestination):
                command を実行できる destination. 既定値は`CommandDestination.BOTH`.

        Returns:
            Callable[[CommandHandler], CommandDefinition]: handler を binding へ変換し、この
            registry へ登録する
            decorator.
        """

        def decorate(handler: CommandHandler) -> CommandDefinition:
            """Handler を definition へ変換し、この registry へ登録する.

            Args:
                handler (CommandHandler):
                    `CommandContext` を受けて optional response text を返す async command
                    handler.

            Returns:
                CommandDefinition: metadata と handler を保持し、登録済みの immutable binding.

            Raises:
                ValueError: outer `name` が空、または case-insensitive に登録済みの場合.
            """
            definition = CommandDefinition(
                metadata=CommandMetadata(
                    name=name,
                    description=description,
                    usage=usage,
                    arguments=arguments,
                    required_privileges=required_privileges,
                    allowed_destinations=allowed_destinations,
                ),
                handler=handler,
            )
            self.register(definition)
            return definition

        return decorate


def command(
    name: str,
    *,
    description: str,
    usage: str = "",
    arguments: tuple[CommandArgument, ...] = (),
    required_privileges: Privileges = Privileges.NONE,
    allowed_destinations: CommandDestination = CommandDestination.BOTH,
) -> Callable[[CommandHandler], CommandDefinition]:
    """Handler から未登録の CommandDefinition を作成する decorator を返す.

    Args:
        name (str): canonical command name. lowercase を推奨する.
        description (str): help output に表示する人間向け説明.
        usage (str): `!roll [max]`のような help 用 usage text. 既定値は空文字列.
        arguments (tuple[CommandArgument, ...]):
            受け付ける argument の metadata. 既定値は空 tuple.
        required_privileges (Privileges):
            command 実行に必要な server-side privilege. 既定値は`Privileges.NONE`.
        allowed_destinations (CommandDestination):
            command を実行できる destination. 既定値は`CommandDestination.BOTH`.

    Returns:
        Callable[[CommandHandler], CommandDefinition]: handler を immutable definition
        へ変換する
        decorator.
    """

    def decorate(handler: CommandHandler) -> CommandDefinition:
        """Handler と outer metadata から未登録の definition を作成する.

        Args:
            handler (CommandHandler):
                `CommandContext` を受けて optional response text を返す async command handler.

        Returns:
            CommandDefinition: registry へは登録せずに作成した immutable metadata と handler
            の binding.
        """
        return CommandDefinition(
            metadata=CommandMetadata(
                name=name,
                description=description,
                usage=usage,
                arguments=arguments,
                required_privileges=required_privileges,
                allowed_destinations=allowed_destinations,
            ),
            handler=handler,
        )

    return decorate
