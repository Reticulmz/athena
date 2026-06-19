from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Protocol, cast

import pytest


def assert_rejects_setattr(instance: object, attribute: str, value: object) -> None:
    """frozen オブジェクトの属性代入不可能性を検証するヘルパー。

    型チェックの警告を発生させずに、実行時の FrozenInstanceError 送出をアサートする。
    """
    with pytest.raises(FrozenInstanceError):
        setattr(instance, attribute, value)


def assert_rejects_setitem(instance: object, index: int, value: object) -> None:
    """immutable sequence の要素代入不可能性を検証するヘルパー。

    型チェックの警告を発生させずに、実行時の TypeError 送出をアサートする。
    """
    with pytest.raises(TypeError):
        cast("_SupportsSetitem", instance)[index] = value


class _SupportsSetitem(Protocol):
    def __setitem__(self, index: int, value: object) -> None: ...
