"""Domain eventの共通基底型を定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Event:
    """不変domain eventが継承する属性なしの共通基底型を表す.

    Notes:
        具体eventはこの型を継承してpayload fieldを追加し,frozen dataclassとして不変に扱う.
    """
