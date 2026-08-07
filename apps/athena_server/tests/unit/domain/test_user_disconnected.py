"""UserDisconnected domain eventの継承,表現,不変性を検証するmodule."""

from __future__ import annotations

from dataclasses import fields

from osu_server.domain.events import Event
from osu_server.domain.events.users import UserDisconnected
from tests.support import assert_rejects_setattr


class TestUserDisconnectedInheritance:
    """UserDisconnectedがEvent基底classを継承するcontractを検証する."""

    def test_is_subclass_of_event(self) -> None:
        """Event typeを必要とするconsumerがclass自体を受け入れることを検証する.

        UserDisconnected classとEvent基底classの継承関係を調べ,
        subclass判定がTrueになることを確認する.

        Returns:
            None: class継承関係を検証して完了し,呼び出し側へ値を返さない.
        """
        assert issubclass(UserDisconnected, Event)

    def test_instance_is_event(self) -> None:
        """生成済み切断eventがEvent instanceとして扱えることを検証する.

        user_id=1のUserDisconnectedを生成してisinstanceを適用し,Event instanceになることを確認する.

        Returns:
            None: instanceのruntime typeを検証して完了し,呼び出し側へ値を返さない.
        """
        event = UserDisconnected(user_id=1)
        assert isinstance(event, Event)


class TestUserDisconnectedImmutability:
    """UserDisconnectedがfrozen slots dataclassであるcontractを検証する."""

    def test_frozen_raises_on_attribute_set(self) -> None:
        """作成済みeventのuser_idを変更できないことを検証する.

        user_id=1のeventを生成し,user_idへ別の値を代入する操作が拒否されることを確認する.

        Returns:
            None: attribute代入拒否を検証して完了し,呼び出し側へ値を返さない.
        """
        event = UserDisconnected(user_id=1)
        assert_rejects_setattr(event, "user_id", 2)

    def test_slots_enabled(self) -> None:
        """Event classがslotsを持ち動的attributeを許さないことを検証する.

        UserDisconnected型を参照して__slots__ attributeの有無を調べ,
        slot定義が公開されていることを確認する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(UserDisconnected, "__slots__")

    def test_no_dict(self) -> None:
        """Slots instanceが__dict__を持たないことを検証する.

        user_id=1のeventを生成して__dict__ attributeを調べ,instance dictionaryがないことを確認する.

        Returns:
            None: instance dictionaryの不在を検証して完了し,呼び出し側へ値を返さない.
        """
        event = UserDisconnected(user_id=1)
        assert not hasattr(event, "__dict__")


class TestUserDisconnectedFields:
    """UserDisconnectedがuser IDを保持するfield contractを検証する."""

    def test_has_user_id_field(self) -> None:
        """Dataclass field一覧にuser_idが含まれることを検証する.

        UserDisconnectedのdataclass field名を一覧化し,user_idが集合に含まれることを確認する.

        Returns:
            None: fieldの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        field_names = [f.name for f in fields(UserDisconnected)]
        assert "user_id" in field_names

    def test_user_id_type_annotation(self) -> None:
        """User ID fieldのannotationがintであることを検証する.

        UserDisconnectedのfield mappingからuser_idを取得し,annotationがintであることを確認する.

        Returns:
            None: field annotationを検証して完了し,呼び出し側へ値を返さない.
        """
        field_map = {f.name: f for f in fields(UserDisconnected)}
        assert field_map["user_id"].type == "int"

    def test_user_id_value(self) -> None:
        """Constructorへ渡したuser IDがevent payloadに保持されることを検証する.

        user_id=42でeventを生成し,payloadから読み出すuser IDが42に一致することを確認する.

        Returns:
            None: payload値の保持を検証して完了し,呼び出し側へ値を返さない.
        """
        event = UserDisconnected(user_id=42)
        assert event.user_id == 42

    def test_equality(self) -> None:
        """同じuser IDを持つevent instanceがvalue equalityを持つことを検証する.

        同じuser IDを持つ二つのeventを生成して比較し,両instanceが等価になることを確認する.

        Returns:
            None: 同値eventの比較結果を検証して完了し,呼び出し側へ値を返さない.
        """
        a = UserDisconnected(user_id=1)
        b = UserDisconnected(user_id=1)
        assert a == b

    def test_inequality(self) -> None:
        """User IDが異なるevent instanceが非等価になることを検証する.

        異なるuser IDを持つ二つのeventを生成して比較し,両instanceが非等価になることを確認する.

        Returns:
            None: 異なるpayloadを持つeventの比較結果を検証して完了し,呼び出し側へ値を返さない.
        """
        a = UserDisconnected(user_id=1)
        b = UserDisconnected(user_id=2)
        assert a != b
