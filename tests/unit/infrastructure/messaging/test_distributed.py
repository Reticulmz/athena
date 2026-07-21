"""分散イベント通知のenvelopeとmapper契約を検証します."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final, override

import pytest

from osu_server.infrastructure.messaging.distributed import (
    DistributedEventEnvelope,
    DistributedEventMapper,
    JsonObject,
    JsonValue,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class _UserDisconnectedNotification:
    """user切断を表すmapper検証用の内部イベントです.

    Attributes:
        user_id (int): 切断したuserの識別子です.
    """

    user_id: int


@final
class _UserDisconnectedMapper(DistributedEventMapper[_UserDisconnectedNotification]):
    """user切断イベントをJSON primitive payloadへ変換するテスト用mapperです.

    Attributes:
        event_type (str): 分散通知に使用する安定イベント型です.
        schema_version (int): payload schemaの互換性versionです.
    """

    event_type = "user.disconnect.v1"
    schema_version = 1

    @override
    def to_payload(self, event: _UserDisconnectedNotification) -> JsonObject:
        """user切断イベントをJSON object payloadへ変換します.

        Args:
            event (_UserDisconnectedNotification): payloadへ変換する内部イベントです.

        Returns:
            JsonObject: user IDだけを含むprimitive payloadです.
        """
        return {"user_id": event.user_id}

    @override
    def from_payload(self, payload: Mapping[str, JsonValue]) -> _UserDisconnectedNotification:
        """JSON object payloadからuser切断イベントを再構築します.

        Args:
            payload (Mapping[str, JsonValue]): 整数のuser_idを含むmapper payloadです.

        Returns:
            _UserDisconnectedNotification: payloadのuser IDを持つ内部イベントです.

        Raises:
            KeyError: payloadにuser_idが存在しない場合.
            AssertionError: payloadのuser_idが整数でない場合.
        """
        user_id = payload["user_id"]
        assert isinstance(user_id, int)
        return _UserDisconnectedNotification(user_id=user_id)


def test_envelope_contains_required_contract_fields() -> None:
    """有効なenvelopeが全必須contract fieldを保持することを検証します.

    Returns:
        None: 入力したevent ID、type、時刻、schema、payloadがそのまま取得できることを表します.
    """
    occurred_at = datetime.now(UTC)

    envelope = DistributedEventEnvelope(
        event_id="event-1",
        event_type="user.disconnect.v1",
        occurred_at=occurred_at,
        schema_version=1,
        payload={"user_id": 1, "reason": None, "tags": ["stable"]},
    )

    assert envelope.event_id == "event-1"
    assert envelope.event_type == "user.disconnect.v1"
    assert envelope.occurred_at == occurred_at
    assert envelope.schema_version == 1
    assert envelope.payload == {"user_id": 1, "reason": None, "tags": ["stable"]}


def test_mapper_round_trips_primitive_payload() -> None:
    """mapperがprimitive payloadを介して内部イベントを往復変換できることを検証します.

    Returns:
        None: 生成payloadと再構築イベントが期待値と一致することを表します.
    """
    mapper = _UserDisconnectedMapper()
    event = _UserDisconnectedNotification(user_id=42)

    payload = mapper.to_payload(event)
    rebuilt = mapper.from_payload(payload)

    assert payload == {"user_id": 42}
    assert rebuilt == event


def test_envelope_rejects_non_primitive_payload() -> None:
    """JSON非対応値を含むpayloadがTypeErrorで拒否されることを検証します.

    Returns:
        None: object値を含むpayloadのenvelope生成が失敗することを表します.
    """
    invalid_payload = cast("JsonObject", {"bad": object()})

    with pytest.raises(TypeError):
        _ = DistributedEventEnvelope(
            event_id="event-1",
            event_type="bad.v1",
            occurred_at=datetime.now(UTC),
            schema_version=1,
            payload=invalid_payload,
        )


def test_envelope_rejects_invalid_schema_version() -> None:
    """非正のschema versionがValueErrorで拒否されることを検証します.

    Returns:
        None: schema_versionが0のenvelope生成が失敗することを表します.
    """
    with pytest.raises(ValueError, match="schema_version"):
        _ = DistributedEventEnvelope(
            event_id="event-1",
            event_type="bad.v1",
            occurred_at=datetime.now(UTC),
            schema_version=0,
            payload={},
        )


def test_contract_is_non_durable_notification() -> None:
    """公開envelope docstringが非永続かつreplayなしのcontract phraseを保持することを検証します.

    Returns:
        None: 既存の英語contract phrase二つが公開docstringに存在することを表します.
    """
    doc = DistributedEventEnvelope.__doc__ or ""
    assert "not a durable source of truth" in doc
    assert "no replay guarantee" in doc
