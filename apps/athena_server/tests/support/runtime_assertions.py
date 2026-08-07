"""immutable objectのruntime拒否契約を検証するassertion helperを提供する."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Protocol, cast

import pytest


def assert_rejects_setattr(instance: object, attribute: str, value: object) -> None:
    """Frozen objectが属性代入を拒否するruntime契約を検証する.

    Args:
        instance (object): 属性代入を試行するfrozen instance.
        attribute (str): 代入を試行するattribute名.
        value (object): attributeへ代入を試行する値.

    Returns:
        None: FrozenInstanceErrorが送出されることをassertして完了する.

    Notes:
        型checkerの静的な代入拒否を回避し, runtime contractだけを検証する.
    """
    with pytest.raises(FrozenInstanceError):
        setattr(instance, attribute, value)


def assert_rejects_setitem(instance: object, index: int, value: object) -> None:
    """Immutable sequenceが要素代入を拒否するruntime契約を検証する.

    Args:
        instance (object): 要素代入を試行するimmutable sequence.
        index (int): 代入を試行するzero-based index.
        value (object): indexへ代入を試行する値.

    Returns:
        None: TypeErrorが送出されることをassertして完了する.

    Notes:
        型checkerの静的な代入拒否を回避し, runtime contractだけを検証する.
    """
    with pytest.raises(TypeError):
        cast("_SupportsSetitem", instance)[index] = value


class _SupportsSetitem(Protocol):
    """item assignmentを受け入れるstructural protocolを表す.

    Notes:
        assertion helperがruntime assignmentを型安全に実行するためだけのprivate protocol.
    """

    def __setitem__(self, index: int, value: object) -> None:
        """指定indexへ値を代入する.

        Args:
            index (int): 代入先のzero-based index.
            value (object): indexへ保存する値.

        Returns:
            None: item assignmentを完了し, 呼び出し側へ値を返さない.
        """
        ...
