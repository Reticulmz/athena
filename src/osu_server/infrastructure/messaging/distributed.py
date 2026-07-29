"""非永続分散通知の契約モデルを定義します."""

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
    """実行環境間の best-effort 通知を包む envelope です.

    Attributes:
        event_id (str): 通知を一意に識別する空でない ID です.
        event_type (str): 購読と mapper が使う空でない安定イベント型です.
        occurred_at (datetime): 通知元でイベントが発生した日時です.
        schema_version (int): payload schema の正の互換性 version です.
        payload (JsonObject): JSON primitive,list,object だけで構成する通知内容です.

    Notes:
        This is not a durable source of truth and has no replay guarantee.
    """

    event_id: str
    event_type: str
    occurred_at: datetime
    schema_version: int
    payload: JsonObject

    def __post_init__(self) -> None:
        """通知 envelope の識別子,schema version,JSON payload を検証します.

        Returns:
            None: 全ての不変条件を満たしたことを表します.

        Raises:
            ValueError: event_id または event_type が空,あるいは schema_version が正でない場合.
            TypeError: payload が JSON object でない,または JSON 非対応値を含む場合.
        """
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
    """内部イベントと分散 payload を相互変換する明示的な契約です.

    Attributes:
        event_type (str): 分散通知で用いる安定したイベント型名です.
        schema_version (int): mapper が扱う payload schema の正の version です.
    """

    event_type: str
    schema_version: int

    def to_payload(self, event: TDistributedEvent) -> JsonObject:
        """内部イベント値を JSON primitive の payload に変換します.

        Args:
            event (TDistributedEvent): 変換対象の内部イベント値です.

        Returns:
            JsonObject: 分散通知に格納できる JSON object です.
        """
        ...

    def from_payload(self, payload: Mapping[str, JsonValue]) -> TDistributedEvent:
        """JSON primitive の payload から内部イベント値を再構築します.

        Args:
            payload (Mapping[str, JsonValue]): mapper の schema version に適合する JSON
                object です.

        Returns:
            TDistributedEvent: 再構築した内部イベント値です.
        """
        ...


class DistributedEventPublisher(Protocol):
    """実行環境間の best-effort 通知を publish する port です."""

    async def publish(self, envelope: DistributedEventEnvelope) -> None:
        """通知 envelope を分散 transport へ publish します.

        Args:
            envelope (DistributedEventEnvelope): 配信する検証済み通知 envelope です.

        Returns:
            None: publish 試行が完了したことを表します.
        """
        ...


class DistributedEventSubscriber(Protocol):
    """実行環境間の best-effort 通知を購読する port です."""

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[DistributedEventEnvelope], Awaitable[None]],
    ) -> None:
        """安定した分散イベント型ごとに handler を購読します.

        Args:
            event_type (str): 購読する安定した分散イベント型名です.
            handler (Callable[[DistributedEventEnvelope], Awaitable[None]]): 通知 envelope
                を非同期で処理する handler です.

        Returns:
            None: handler の購読登録が完了したことを表します.
        """
        ...


def _validate_json_object(value: object) -> None:
    """値が文字列 key を持つ JSON object であることを再帰的に検証します.

    Args:
        value (object): 検証する候補値です.

    Returns:
        None: 値が JSON object として有効であることを表します.

    Raises:
        TypeError: 値が dict でない,key が文字列でない,または子要素が JSON 非対応の場合.
    """
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
    """値が JSON primitive,list,または object であることを検証します.

    Args:
        value (object): 検証する候補値です.

    Returns:
        None: 値が JSON 値として有効であることを表します.

    Raises:
        TypeError: 値または子要素が JSON で表現できない場合.
    """
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
