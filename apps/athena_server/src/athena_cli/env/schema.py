"""AppConfig schemaをenvironment file用metadataへ変換する."""

from __future__ import annotations

import json
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
    """AppConfig fieldから導出したenvironment generation metadataを表す.

    Attributes:
        field_name (str): AppConfig上のfield名.
        env_var (str): 対応する環境変数名.
        required (bool): AppConfig validation上で必須の場合はTrue.
        default (str | None): 必須でないfieldの文字列化済みdefault. 必須fieldはNone.
        secret (bool): 表示時にmaskするsecret系fieldの場合はTrue.
        list_like (bool): comma separated valueとして扱うlist fieldの場合はTrue.
        empty_value_is_unset (bool): 空文字を未指定として扱うfieldの場合はTrue.
    """

    field_name: str
    env_var: str
    required: bool
    default: str | None
    secret: bool
    list_like: bool
    empty_value_is_unset: bool


def get_config_env_metadata() -> tuple[EnvFieldMetadata, ...]:
    """AppConfigの全fieldをenvironment file用metadataへ変換する.

    Returns:
        tuple[EnvFieldMetadata, ...]: AppConfig定義順のenvironment file用metadata.
    """
    return tuple(
        _metadata_for_field(field_name, field)
        for field_name, field in AppConfig.model_fields.items()
    )


def render_config_example() -> str:
    """AppConfig schema由来の`.env.example`形式textを生成する.

    Returns:
        str: 各環境変数を1行ずつ含むnewline区切りのexample内容.
    """
    return "\n".join(
        f"{field.env_var}={field.default or ''}" for field in get_config_env_metadata()
    )


def _metadata_for_field(field_name: str, field: FieldInfo) -> EnvFieldMetadata:
    """1つのAppConfig fieldをenvironment file用metadataへ変換する.

    Args:
        field_name (str): AppConfig上のfield名.
        field (FieldInfo): Pydanticが保持するfield metadata.

    Returns:
        EnvFieldMetadata: environment variable名と生成policyを含むmetadata.
    """
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
    """Pydantic fieldのdefaultをenvironment fileへ書ける文字列へ変換する.

    Args:
        field (FieldInfo): default値を保持するPydantic field metadata.

    Returns:
        str: Noneは空文字へ変換しlistはcomma区切りにしたdefault文字列.
    """
    default_value = cast("object", field.get_default(call_default_factory=True))
    if default_value is None:
        return ""
    if isinstance(default_value, bool):
        return str(default_value).lower()
    if isinstance(default_value, list):
        items = cast("Sequence[object]", default_value)
        return json.dumps([str(item) for item in items])
    return str(default_value)


def _is_secret_field(field_name: str) -> bool:
    """AppConfig field名がsecretを含む表示mask対象か判定する.

    Args:
        field_name (str): 判定するAppConfig field名.

    Returns:
        bool: passwordまたはsecretまたはaccess keyを示す語を含む場合はTrue.
    """
    return any(part in field_name for part in _SECRET_NAME_PARTS)


def _is_list_like(annotation: object) -> bool:
    """Field annotationがlist値としてenvironment fileから読む型か判定する.

    Args:
        annotation (object): Pydantic fieldが保持する型annotation.

    Returns:
        bool: Annotatedを除いた型がlistまたはlist[...]の場合はTrue.
    """
    unwrapped = _unwrap_annotated(annotation)
    return get_origin(unwrapped) is list or unwrapped is list


def _is_optional_bool(annotation: object) -> bool:
    """Field annotationがNoneを許可するbool型か判定する.

    Args:
        annotation (object): Pydantic fieldが保持する型annotation.

    Returns:
        bool: Annotatedを除いたunionがboolとNoneTypeを含む場合はTrue.
    """
    unwrapped = _unwrap_annotated(annotation)
    args = set(get_args(unwrapped))
    return bool in args and NoneType in args


def _unwrap_annotated(annotation: object) -> object:
    """Annotated型から基底annotationだけを取り出す.

    Args:
        annotation (object): Annotatedを含む可能性がある型annotation.

    Returns:
        object: Annotatedの場合は先頭の基底型. それ以外は入力値そのもの.
    """
    if get_origin(annotation) is Annotated:
        return cast("object", get_args(annotation)[0])
    return annotation
