from __future__ import annotations

from dataclasses import dataclass
from types import NoneType
from typing import TYPE_CHECKING, Annotated, cast, get_args, get_origin

from osu_server.config import AppConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic.fields import FieldInfo


_SECRET_NAME_PARTS = ("password", "secret", "access_key")


@dataclass(frozen=True, slots=True)
class EnvFieldMetadata:
    """AppConfig field から導出した env generation metadata.

    Attributes:
        field_name: AppConfig 上の field 名.
        env_var: 対応する環境変数名.
        required: AppConfig validation 上で必須の場合は true.
        default: 必須でない field の文字列化済み default. 必須 field は None.
        secret: 表示時に mask する secret 系 field の場合は true.
        list_like: comma separated value として扱う list field の場合は true.
        empty_value_is_unset: 空文字を未指定として扱う field の場合は true.
    """

    field_name: str
    env_var: str
    required: bool
    default: str | None
    secret: bool
    list_like: bool
    empty_value_is_unset: bool


def get_config_env_metadata() -> tuple[EnvFieldMetadata, ...]:
    return tuple(
        _metadata_for_field(field_name, field)
        for field_name, field in AppConfig.model_fields.items()
    )


def render_config_example() -> str:
    return "\n".join(
        f"{field.env_var}={field.default or ''}" for field in get_config_env_metadata()
    )


def _metadata_for_field(field_name: str, field: FieldInfo) -> EnvFieldMetadata:
    required = field.is_required()
    return EnvFieldMetadata(
        field_name=field_name,
        env_var=field_name.upper(),
        required=required,
        default=None if required else _stringify_default(field),
        secret=_is_secret_field(field_name),
        list_like=_is_list_like(field.annotation),
        empty_value_is_unset=_is_optional_bool(field.annotation),
    )


def _stringify_default(field: FieldInfo) -> str:
    default_value = cast("object", field.get_default(call_default_factory=True))
    if default_value is None:
        return ""
    if isinstance(default_value, bool):
        return str(default_value).lower()
    if isinstance(default_value, list):
        items = cast("Sequence[object]", default_value)
        return ",".join(str(item) for item in items)
    return str(default_value)


def _is_secret_field(field_name: str) -> bool:
    return any(part in field_name for part in _SECRET_NAME_PARTS)


def _is_list_like(annotation: object) -> bool:
    unwrapped = _unwrap_annotated(annotation)
    return get_origin(unwrapped) is list or unwrapped is list


def _is_optional_bool(annotation: object) -> bool:
    unwrapped = _unwrap_annotated(annotation)
    args = set(get_args(unwrapped))
    return bool in args and NoneType in args


def _unwrap_annotated(annotation: object) -> object:
    if get_origin(annotation) is Annotated:
        return cast("object", get_args(annotation)[0])
    return annotation
