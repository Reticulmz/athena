"""Contract-only model for non-durable distributed notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from datetime import datetime

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]

TDistributedEvent = TypeVar("TDistributedEvent", bound=object)


@dataclass(frozen=True, slots=True)
class DistributedEventEnvelope:
    """Envelope for best-effort cross-runtime notifications.

    This is not a durable source of truth and has no replay guarantee.
    """

    event_id: str
    event_type: str
    occurred_at: datetime
    schema_version: int
    payload: JsonObject

    def __post_init__(self) -> None:
        if not self.event_id:
            msg = "event_id must not be empty"
            raise ValueError(msg)
        if not self.event_type:
            msg = "event_type must not be empty"
            raise ValueError(msg)
        if self.schema_version <= 0:
            msg = "schema_version must be positive"
            raise ValueError(msg)
        _validate_json_object(self.payload)


class DistributedEventMapper(Protocol[TDistributedEvent]):
    """Explicit conversion contract between internal events and payloads."""

    event_type: str
    schema_version: int

    def to_payload(self, event: TDistributedEvent) -> JsonObject:
        """Convert an internal event value to a primitive payload."""
        ...

    def from_payload(self, payload: Mapping[str, JsonValue]) -> TDistributedEvent:
        """Rebuild an internal event value from a primitive payload."""
        ...


class DistributedEventPublisher(Protocol):
    """Publisher port for best-effort distributed notifications."""

    async def publish(self, envelope: DistributedEventEnvelope) -> None:
        """Publish a notification envelope."""
        ...


class DistributedEventSubscriber(Protocol):
    """Subscriber port for best-effort distributed notifications."""

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[DistributedEventEnvelope], Awaitable[None]],
    ) -> None:
        """Subscribe a handler by stable distributed event type."""
        ...


def _validate_json_object(value: object) -> None:
    if not isinstance(value, dict):
        msg = "payload must be a dict"
        raise TypeError(msg)
    payload = cast("dict[object, object]", value)
    for key, child in payload.items():
        if not isinstance(key, str):
            msg = "payload keys must be strings"
            raise TypeError(msg)
        _validate_json_value(child)


def _validate_json_value(value: object) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        items = cast("list[object]", value)
        for child in items:
            _validate_json_value(child)
        return
    if isinstance(value, dict):
        _validate_json_object(cast("dict[object, object]", value))
        return
    msg = f"payload contains non-primitive value: {type(value).__name__}"
    raise TypeError(msg)
