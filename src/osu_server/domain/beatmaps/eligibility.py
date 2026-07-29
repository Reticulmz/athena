"""Beatmap提出適格性の値objectを定義するmodule."""

from dataclasses import dataclass
from enum import IntEnum


class BeatmapStatus(IntEnum):
    """Beatmapの提出適格性を表す整数statusを定義する.

    Attributes:
        NOT_SUBMITTED (int): not submitted statusを表す値.
        PENDING (int): pending statusを表す値.
        RANKED (int): ranked statusを表す値.
        APPROVED (int): approved statusを表す値.
        QUALIFIED (int): qualified statusを表す値.
        LOVED (int): loved statusを表す値.
        WIP (int): work in progress statusを表す値.
        GRAVEYARD (int): graveyard statusを表す値.
        UNKNOWN (int): unknown statusを表す値.
    """

    NOT_SUBMITTED = -1
    PENDING = 0
    RANKED = 1
    APPROVED = 2
    QUALIFIED = 3
    LOVED = 4
    WIP = 5
    GRAVEYARD = 6
    UNKNOWN = 7


@dataclass(slots=True, frozen=True)
class EligibilityResult:
    """Beatmapの提出適格性判定結果を表す.

    Attributes:
        eligible (bool): 提出を受け付けるか.
        status (BeatmapStatus): 判定に使用したbeatmap status.
        reason (str | None): 不適格とした理由. 適格な場合はNone.
    """

    eligible: bool
    status: BeatmapStatus
    reason: str | None = None
