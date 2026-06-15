"""Tests for distributed event contracts."""

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
    user_id: int


@final
class _UserDisconnectedMapper(DistributedEventMapper[_UserDisconnectedNotification]):
    event_type = "user.disconnect.v1"
    schema_version = 1

    @override
    def to_payload(self, event: _UserDisconnectedNotification) -> JsonObject:
        return {"user_id": event.user_id}

    @override
    def from_payload(self, payload: Mapping[str, JsonValue]) -> _UserDisconnectedNotification:
        user_id = payload["user_id"]
        assert isinstance(user_id, int)
        return _UserDisconnectedNotification(user_id=user_id)


def test_envelope_contains_required_contract_fields() -> None:
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
    mapper = _UserDisconnectedMapper()
    event = _UserDisconnectedNotification(user_id=42)

    payload = mapper.to_payload(event)
    rebuilt = mapper.from_payload(payload)

    assert payload == {"user_id": 42}
    assert rebuilt == event


def test_envelope_rejects_non_primitive_payload() -> None:
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
    with pytest.raises(ValueError, match="schema_version"):
        _ = DistributedEventEnvelope(
            event_id="event-1",
            event_type="bad.v1",
            occurred_at=datetime.now(UTC),
            schema_version=0,
            payload={},
        )


def test_contract_is_non_durable_notification() -> None:
    doc = DistributedEventEnvelope.__doc__ or ""
    assert "not a durable source of truth" in doc
    assert "no replay guarantee" in doc
