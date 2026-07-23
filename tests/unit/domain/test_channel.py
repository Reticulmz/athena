"""Channel domain modelとChannelType enumの契約を検証するmodule.

Required fieldとchannel名validationおよびrole based access controlのvalue objectを対象にする.
"""

# ruff: noqa: A002
from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from enum import Enum

import pytest

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
from tests.factories.domain import make_channel

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _make_channel(
    *,
    id: int = 1,
    name: str = "#osu",
    topic: str = "General discussion",
    channel_type: ChannelType = ChannelType.PUBLIC,
    auto_join: bool = True,
    rate_limit_messages: int | None = None,
    rate_limit_window: int | None = None,
    created_at: datetime = _NOW,
    updated_at: datetime = _NOW,
) -> Channel:
    """Channel testで使うdomain modelを指定状態で作る.

    Args:
        id (int): 永続channel ID.
        name (str): #で始まるchannel名.
        topic (str): channelの説明文.
        channel_type (ChannelType): channel用途の分類.
        auto_join (bool): login時に自動参加させるか.
        rate_limit_messages (int | None): rate limit内で許可するmessage数.
        rate_limit_window (int | None): rate limitを測る時間window.
        created_at (datetime): channelを作成した日時.
        updated_at (datetime): channelを更新した日時.

    Returns:
        Channel: factoryが生成した指定状態のchannel.

    Raises:
        ValueError: nameがchannel命名規則を満たさない場合.
    """
    return make_channel(
        id=id,
        name=name,
        topic=topic,
        channel_type=channel_type,
        auto_join=auto_join,
        rate_limit_messages=rate_limit_messages,
        rate_limit_window=rate_limit_window,
        created_at=created_at,
        updated_at=updated_at,
    )


# ===========================================================================
# ChannelType enum
# ===========================================================================


class TestChannelType:
    """ChannelTypeの公開値と予約値の閉集合を検証するtest群."""

    def test_is_enum(self) -> None:
        """ChannelTypeが用途分類のEnumであることを検証する.

        ChannelTypeをEnum subclassとして確認し自由文字列ではなく閉集合で用途を表すことを確認する.

        Returns:
            None: ChannelType enum型の検証を完了する.
        """
        assert issubclass(ChannelType, Enum)

    def test_public_value(self) -> None:
        """PUBLIC memberが公開channelの永続値を持つことを検証する.

        PUBLICのvalueを比較しrepositoryやmapperが使うpublic文字列が変わらないことを確認する.

        Returns:
            None: public channel値の検証を完了する.
        """
        assert ChannelType.PUBLIC.value == "public"

    def test_reserved_variants_exist(self) -> None:
        """予約済みChannelType memberが将来の用途として存在することを検証する.

        MULTIPLAYERとSPECTATORおよびTEMPORARYの値を確認し用途別channelを表現できることを確認する.

        Returns:
            None: 予約channel種別の検証を完了する.
        """
        assert ChannelType.MULTIPLAYER.value == "multiplayer"
        assert ChannelType.SPECTATOR.value == "spectator"
        assert ChannelType.TEMPORARY.value == "temporary"

    def test_total_member_count(self) -> None:
        """ChannelTypeに予定外のmemberが追加されていないことを検証する.

        enumの長さを既知の四種別と比較しstorageに保存する閉集合が増減していないことを確認する.

        Returns:
            None: channel種別数の検証を完了する.
        """
        assert len(ChannelType) == 4


# ===========================================================================
# Channel dataclass
# ===========================================================================


class TestChannelDataclass:
    """Channel dataclassの構造とfield保持を検証するtest群."""

    def test_slots_enabled(self) -> None:
        """Channelがslotを利用するdomain modelであることを検証する.

        型定義を調べて__slots__が存在しchannel instanceが定義済みfieldだけを持つことを確認する.

        Returns:
            None: Channel slot利用の検証を完了する.
        """
        assert hasattr(Channel, "__slots__")

    def test_creation(self) -> None:
        """Channelが作成時に全domain fieldを保持することを検証する.

        標準fixtureを生成しidentityとtopicおよびrate limit設定が取得できることを確認する.

        Returns:
            None: Channel field保持の検証を完了する.
        """
        ch = _make_channel()
        assert ch.id == 1
        assert ch.name == "#osu"
        assert ch.topic == "General discussion"
        assert ch.channel_type == ChannelType.PUBLIC
        assert ch.auto_join is True
        assert ch.rate_limit_messages is None
        assert ch.rate_limit_window is None
        assert ch.created_at == _NOW
        assert ch.updated_at == _NOW

    def test_all_expected_fields(self) -> None:
        """Channel dataclassが固定したfield集合を持つことを検証する.

        dataclass field名を期待集合と比較しaccess policy fieldの欠落や追加がないことを確認する.

        Returns:
            None: Channel field集合の検証を完了する.
        """
        expected = {
            "id",
            "name",
            "topic",
            "channel_type",
            "auto_join",
            "rate_limit_messages",
            "rate_limit_window",
            "created_at",
            "updated_at",
        }
        actual = {f.name for f in fields(Channel)}
        assert actual == expected

    def test_rate_limit_nullable(self) -> None:
        """Channelが任意のrate limit設定を保持することを検証する.

        message数と時間windowを指定して生成しrate limit設定がそのまま観測できることを確認する.

        Returns:
            None: rate limit保持の検証を完了する.
        """
        ch = _make_channel(rate_limit_messages=5, rate_limit_window=30)
        assert ch.rate_limit_messages == 5
        assert ch.rate_limit_window == 30


# ===========================================================================
# Channel name validation
# ===========================================================================


class TestChannelNameValidation:
    """Channel名の# prefixと許可文字制約を検証するtest群."""

    def test_valid_names(self) -> None:
        """許可されたchannel名がそのまま生成できることを検証する.

        英小文字と数字およびhyphenとunderscoreを含む名前を渡し各nameが保持されることを確認する.

        Returns:
            None: 有効channel名の検証を完了する.
        """
        for name in ("#osu", "#announce", "#lobby-1", "#multi_room", "#a123"):
            ch = _make_channel(name=name)
            assert ch.name == name

    def test_missing_hash_prefix(self) -> None:
        """# prefixがないchannel名を拒否することを検証する.

        osuというbare nameで生成を試みてValueErrorがprefix違反を示すことを確認する.

        Returns:
            None: prefix欠落拒否の検証を完了する.
        """
        with pytest.raises(ValueError, match="must start with '#'"):
            _ = _make_channel(name="osu")

    def test_empty_after_hash(self) -> None:
        """#だけのchannel名を拒否することを検証する.

        bodyを持たない名前で生成を試みてValueErrorが最低一文字の制約を示すことを確認する.

        Returns:
            None: 空channel body拒否の検証を完了する.
        """
        with pytest.raises(ValueError, match="at least one character after '#'"):
            _ = _make_channel(name="#")

    def test_uppercase_rejected(self) -> None:
        """大文字を含むchannel名を拒否することを検証する.

        #OSUを渡して生成を試みてlowercase-onlyの文字制約がValueErrorになることを確認する.

        Returns:
            None: 大文字channel名拒否の検証を完了する.
        """
        with pytest.raises(ValueError, match="invalid characters"):
            _ = _make_channel(name="#OSU")

    def test_space_rejected(self) -> None:
        """空白を含むchannel名を拒否することを検証する.

        #osu chatを渡して生成を試みてname bodyに空白を含められないことを確認する.

        Returns:
            None: 空白channel名拒否の検証を完了する.
        """
        with pytest.raises(ValueError, match="invalid characters"):
            _ = _make_channel(name="#osu chat")

    def test_special_chars_rejected(self) -> None:
        """許可集合外のspecial characterを含むchannel名を拒否することを検証する.

        記号を含む複数の名前で生成を試みて各入力がValueErrorになることを確認する.

        Returns:
            None: special character拒否の検証を完了する.
        """
        for name in ("#osu!", "#a@b", "#chan.el", "#ch/an"):
            with pytest.raises(ValueError, match="invalid characters"):
                _ = _make_channel(name=name)

    def test_hyphen_allowed(self) -> None:
        """Hyphenを含むchannel名が許可されることを検証する.

        #my-channelを生成しa-z0-9_-の許可集合にhyphenが含まれることを確認する.

        Returns:
            None: hyphen許可の検証を完了する.
        """
        ch = _make_channel(name="#my-channel")
        assert ch.name == "#my-channel"

    def test_underscore_allowed(self) -> None:
        """Underscoreを含むchannel名が許可されることを検証する.

        #my_channelを生成しa-z0-9_-の許可集合にunderscoreが含まれることを確認する.

        Returns:
            None: underscore許可の検証を完了する.
        """
        ch = _make_channel(name="#my_channel")
        assert ch.name == "#my_channel"

    def test_digits_allowed(self) -> None:
        """数字を含むchannel名が許可されることを検証する.

        #room42を生成しa-z0-9_-の許可集合に数字が含まれることを確認する.

        Returns:
            None: 数字許可の検証を完了する.
        """
        ch = _make_channel(name="#room42")
        assert ch.name == "#room42"


# ===========================================================================
# ChannelRoleOverride dataclass
# ===========================================================================


class TestChannelRoleOverride:
    """ChannelRoleOverrideのrole別access制約を検証するtest群."""

    def test_slots_enabled(self) -> None:
        """ChannelRoleOverrideがslotを利用するvalue objectであることを検証する.

        型定義を調べて__slots__が存在しaccess overrideが定義済みfieldだけを持つことを確認する.

        Returns:
            None: role override slot利用の検証を完了する.
        """
        assert hasattr(ChannelRoleOverride, "__slots__")

    def test_creation(self) -> None:
        """ChannelRoleOverrideがreadとwrite許可を保持することを検証する.

        channelとroleの組にaccess flagを指定しauthorization判断用fieldが取得できることを確認する.

        Returns:
            None: role override生成の検証を完了する.
        """
        ov = ChannelRoleOverride(channel_id=1, role_id=2, can_read=True, can_write=False)
        assert ov.channel_id == 1
        assert ov.role_id == 2
        assert ov.can_read is True
        assert ov.can_write is False

    def test_fields(self) -> None:
        """ChannelRoleOverrideが固定したaccess control field集合を持つことを検証する.

        dataclass field名をchannel IDとrole IDおよびread/write flagの期待集合と比較する.

        Returns:
            None: role override field集合の検証を完了する.
        """
        expected = {"channel_id", "role_id", "can_read", "can_write"}
        actual = {f.name for f in fields(ChannelRoleOverride)}
        assert actual == expected
