"""BanchoBot command contextとmetadata value objectの契約を検証するmodule.

Commandの宛先制約と不変metadataおよびhandler入力snapshotを対象にする.
"""

from __future__ import annotations

from osu_server.domain.chat.commands import (
    CommandArgument,
    CommandContext,
    CommandDestination,
    CommandMetadata,
)
from osu_server.domain.identity.authorization import Privileges
from tests.support.runtime_assertions import assert_rejects_setattr, assert_rejects_setitem


class TestCommandDestination:
    """CommandDestinationのstable宛先値契約を検証するtest群."""

    def test_channel_value(self) -> None:
        """CHANNELがchannel内実行を表す文字列値であることを検証する.

        CHANNEL memberを比較しcommand dispatcherが使うchannel値が観測できることを確認する.

        Returns:
            None: channel宛先値の検証を完了する.
        """
        assert CommandDestination.CHANNEL == "channel"

    def test_pm_value(self) -> None:
        """PMがprivate message実行を表す文字列値であることを検証する.

        PM memberを比較しcommand dispatcherが使うprivate message値が観測できることを確認する.

        Returns:
            None: private message宛先値の検証を完了する.
        """
        assert CommandDestination.PM == "pm"

    def test_both_value(self) -> None:
        """BOTHが両方の宛先を許可する文字列値であることを検証する.

        BOTH memberを比較しchannelとprivate message両用の設定値が観測できることを確認する.

        Returns:
            None: 両宛先値の検証を完了する.
        """
        assert CommandDestination.BOTH == "both"

    def test_is_str_enum(self) -> None:
        """CommandDestination memberが文字列として利用できることを検証する.

        CHANNEL memberにisinstanceを適用しwire destinationへ直接渡せるstr互換性を確認する.

        Returns:
            None: str互換性の検証を完了する.
        """
        assert isinstance(CommandDestination.CHANNEL, str)


class TestCommandArgument:
    """CommandArgumentの引数metadata保持と不変性を検証するtest群."""

    def test_create(self) -> None:
        """任意引数metadataが名前と説明を保持することを検証する.

        max引数をrequired=Falseで生成し各fieldがusage表示用の入力と一致することを確認する.

        Returns:
            None: 引数metadata保持の検証を完了する.
        """
        arg = CommandArgument(name="max", required=False, description="Maximum value")
        assert arg.name == "max"
        assert arg.required is False
        assert arg.description == "Maximum value"

    def test_required_arg(self) -> None:
        """必須引数metadataがrequired状態を保持することを検証する.

        username引数をrequired=Trueで生成しhandler前の入力要件が観測できることを確認する.

        Returns:
            None: 必須引数状態の検証を完了する.
        """
        arg = CommandArgument(name="username", required=True, description="Target user")
        assert arg.required is True

    def test_is_immutable(self) -> None:
        """CommandArgumentが生成後に変更できないことを検証する.

        生成済みmetadataのnameへ代入を試みてfrozen value objectとして拒否されることを確認する.

        Returns:
            None: 引数metadata不変性の検証を完了する.
        """
        arg = CommandArgument(name="max", required=False, description="Maximum value")
        assert_rejects_setattr(arg, "name", "min")


class TestCommandMetadata:
    """CommandMetadataの発見用fieldとdefault制約を検証するtest群."""

    def test_create_minimal(self) -> None:
        """最小のcommand metadataがnameとdescriptionで生成できることを検証する.

        nameとdescriptionだけを指定しcommand一覧へ表示する二つのfieldが保持されることを確認する.

        Returns:
            None: 最小metadata生成の検証を完了する.
        """
        meta = CommandMetadata(name="roll", description="Roll a random number")
        assert meta.name == "roll"
        assert meta.description == "Roll a random number"

    def test_default_usage_is_empty(self) -> None:
        """未指定のusageが空文字列になることを検証する.

        help commandのmetadataをusageなしで生成し追加のusage表示を要求しないことを確認する.

        Returns:
            None: default usageの検証を完了する.
        """
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.usage == ""

    def test_default_arguments_is_empty(self) -> None:
        """未指定のargumentsが空tupleになることを検証する.

        引数を持たないhelp commandを生成し不変の空argument列が観測できることを確認する.

        Returns:
            None: default argument列の検証を完了する.
        """
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.arguments == ()

    def test_default_required_privileges_is_none(self) -> None:
        """未指定のrequired_privilegesがpublic commandを表すことを検証する.

        privilegeを与えずmetadataを生成しPrivileges.NONEがauthorization inputになることを確認する.

        Returns:
            None: default privilegeの検証を完了する.
        """
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.required_privileges == Privileges.NONE

    def test_default_allowed_destinations_is_both(self) -> None:
        """未指定のallowed_destinationsが両宛先を許可することを検証する.

        destinationを与えずmetadataを生成しBOTHが両宛先のdefaultになることを確認する.

        Returns:
            None: default destinationの検証を完了する.
        """
        meta = CommandMetadata(name="help", description="Show help")
        assert meta.allowed_destinations == CommandDestination.BOTH

    def test_explicit_required_privileges(self) -> None:
        """指定したrequired_privilegesがcommand実行要件になることを検証する.

        ADMINを指定したmetadataを生成しdispatcherが読むprivilege bitmaskが保持されることを確認する.

        Returns:
            None: 明示privilegeの検証を完了する.
        """
        meta = CommandMetadata(
            name="admin_cmd",
            description="Admin only",
            required_privileges=Privileges.ADMIN,
        )
        assert meta.required_privileges == Privileges.ADMIN

    def test_explicit_allowed_destinations(self) -> None:
        """指定したallowed_destinationsがcommandの実行場所を制限することを検証する.

        PMを指定してmetadataを生成しprivate message向け設定が保持されることを確認する.

        Returns:
            None: 明示destinationの検証を完了する.
        """
        meta = CommandMetadata(
            name="pm_only",
            description="PM only",
            allowed_destinations=CommandDestination.PM,
        )
        assert meta.allowed_destinations == CommandDestination.PM

    def test_with_usage(self) -> None:
        """指定したusage文字列がhelp表示用に保持されることを検証する.

        roll commandのusageを指定してmetadataから同じ入力構文を取得できることを確認する.

        Returns:
            None: usage保持の検証を完了する.
        """
        meta = CommandMetadata(name="roll", description="Roll", usage="!roll [max]")
        assert meta.usage == "!roll [max]"

    def test_with_arguments(self) -> None:
        """指定したarguments tupleが順序を保って保持されることを検証する.

        max引数tupleを指定してmetadataが同じobjectを保持することを確認する.

        Returns:
            None: argument列保持の検証を完了する.
        """
        args = (CommandArgument(name="max", required=False, description="Max"),)
        meta = CommandMetadata(name="roll", description="Roll", arguments=args)
        assert meta.arguments == args

    def test_is_immutable(self) -> None:
        """CommandMetadataが生成後に変更できないことを検証する.

        nameへ代入を試みて発見metadataがfrozen objectとして拒否することを確認する.

        Returns:
            None: command metadata不変性の検証を完了する.
        """
        meta = CommandMetadata(name="roll", description="roll")
        assert_rejects_setattr(meta, "name", "new_name")


class TestCommandContext:
    """CommandContextのhandler入力snapshotと不変性を検証するtest群."""

    @staticmethod
    def _make_available_commands() -> tuple[CommandMetadata, ...]:
        """Context testで利用する安定したcommand metadata列を作る.

        Returns:
            tuple[CommandMetadata, ...]: rollとhelpを順序付きで持つ不変command列.
        """
        return (
            CommandMetadata(name="roll", description="Roll a random number"),
            CommandMetadata(name="help", description="Show available commands"),
        )

    def test_create_with_all_fields(self) -> None:
        """CommandContextがhandlerに必要な全入力fieldを保持することを検証する.

        senderとtargetおよびargumentを指定して生成しhandlerが読む全fieldが同じ値で観測できることを確認する.

        Returns:
            None: 全field保持の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=("50",),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.sender_id == 100
        assert ctx.sender_name == "User"
        assert ctx.target == "#osu"
        assert ctx.command_name == "roll"
        assert ctx.args == ("50",)
        assert ctx.destination == CommandDestination.CHANNEL
        assert ctx.available_commands == available

    def test_destination_channel_when_target_has_hash(self) -> None:
        """Channel targetを持つcontextがCHANNEL destinationを保持することを検証する.

        #で始まるtargetを指定してchannel handler向け宛先値が保持されることを確認する.

        Returns:
            None: channel destination保持の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.destination == CommandDestination.CHANNEL

    def test_destination_pm_when_target_no_hash(self) -> None:
        """Private message targetを持つcontextがPM destinationを保持することを検証する.

        user名targetを指定してprivate message handler向け宛先値が保持されることを確認する.

        Returns:
            None: private message destination保持の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="BanchoBot",
            command_name="roll",
            args=(),
            destination=CommandDestination.PM,
            available_commands=available,
        )
        assert ctx.destination == CommandDestination.PM

    def test_args_preserves_order(self) -> None:
        """CommandContext.argsが入力順を保つというparser契約を検証する.

        複数のargumentを指定して生成しindexごとに同じ順序の値を取得できることを確認する.

        Returns:
            None: argument順序保持の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="dummy",
            args=("first", "second", "100", "last"),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.args == ("first", "second", "100", "last")
        assert ctx.args[0] == "first"
        assert ctx.args[1] == "second"
        assert ctx.args[2] == "100"
        assert ctx.args[3] == "last"

    def test_empty_args(self) -> None:
        """引数なしcommandが空tupleのargsを持つことを検証する.

        help commandを空argument列で生成しhandlerが特別なNone処理を必要としないことを確認する.

        Returns:
            None: 空argument列の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="help",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.args == ()

    def test_is_immutable(self) -> None:
        """CommandContextが生成後に変更できないinput snapshotであることを検証する.

        sender_idへ代入を試みて共有contextがfrozen objectとして拒否することを確認する.

        Returns:
            None: context不変性の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert_rejects_setattr(ctx, "sender_id", 999)

    def test_is_immutable_args(self) -> None:
        """CommandContext.argsの要素を変更できないことを検証する.

        複数argumentを持つcontextのtupleへ代入を試みてparser入力順が変更不能であることを確認する.

        Returns:
            None: argument列不変性の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=("a", "b"),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert_rejects_setitem(ctx.args, 0, "x")

    def test_is_immutable_available_commands(self) -> None:
        """CommandContext.available_commandsの要素を変更できないことを検証する.

        command snapshot tupleへ代入を試みて利用可能command集合が変更不能であることを確認する.

        Returns:
            None: command snapshot不変性の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=100,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert_rejects_setitem(
            ctx.available_commands,
            0,
            CommandMetadata(name="x", description="x"),
        )

    def test_sender_identity_captures_id_and_name(self) -> None:
        """CommandContextがsender IDと表示名をhandlerへ渡すことを検証する.

        一意なsender値で生成しauthorizationとresponse生成に必要な二つのidentity fieldを確認する.

        Returns:
            None: sender identity保持の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=42,
            sender_name="PlayerOne",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.sender_id == 42
        assert ctx.sender_name == "PlayerOne"

    def test_destination_captured_in_target(self) -> None:
        """CommandContext.targetがchannel名またはprivate message宛先を保持することを検証する.

        channelとprivate messageのcontextを生成しtargetとdestinationの組が区別できることを確認する.

        Returns:
            None: target宛先保持の検証を完了する.
        """
        available = self._make_available_commands()
        ctx_channel = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="roll",
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx_channel.target == "#osu"
        assert ctx_channel.destination == CommandDestination.CHANNEL

        ctx_pm = CommandContext(
            sender_id=1,
            sender_name="User",
            target="BanchoBot",
            command_name="roll",
            args=(),
            destination=CommandDestination.PM,
            available_commands=available,
        )
        assert ctx_pm.target == "BanchoBot"
        assert ctx_pm.destination == CommandDestination.PM

    def test_command_name_captures_canonical_name(self) -> None:
        """CommandContextが解決済みcanonical command名を保持することを検証する.

        lower-caseのrollを指定して生成しhandlerがaliasではなく正規化済みnameを取得できることを確認する.

        Returns:
            None: canonical command名保持の検証を完了する.
        """
        available = self._make_available_commands()
        ctx = CommandContext(
            sender_id=1,
            sender_name="User",
            target="#osu",
            command_name="roll",  # canonical, lower-case
            args=(),
            destination=CommandDestination.CHANNEL,
            available_commands=available,
        )
        assert ctx.command_name == "roll"
