"""Stable client status values."""

from dataclasses import dataclass
from enum import IntEnum


class StableStatus(IntEnum):
    """Stable client の Status wire 値を表す。"""

    Idle = 0
    Afk = 1
    Playing = 2
    Editing = 3
    Modding = 4
    Multiplayer = 5
    Watching = 6
    Unknown = 7
    Testing = 8
    Submitting = 9
    Paused = 10
    Lobby = 11
    Multiplaying = 12
    OsuDirect = 13


@dataclass(frozen=True, slots=True)
class StableUserStatus:
    """Stable USER_STATS に載せる current status fields。

    引数:
        status: Stable Status の wire 値。
        status_text: Client が送った status text。
        beatmap_md5: Client が送った beatmap md5。未設定なら空文字。
        mods: Stable mods bitmask。
        play_mode: Stable Mode の wire 値。
        beatmap_id: Client が送った beatmap id。未設定なら 0。

    戻り値:
        dataclass のため値そのものを返さない。

    例外:
        現時点では wire parser 済みの値を保持するだけなので独自例外は送出しない。

    制約:
        Bancho wire 型ではなく、transport から domain-compatible state へ写した値として扱う。
    """

    status: int
    status_text: str
    beatmap_md5: str
    mods: int
    play_mode: int
    beatmap_id: int

    def with_play_mode(self, play_mode: int) -> "StableUserStatus":
        """play_mode だけ差し替えた current status を返す。"""
        return StableUserStatus(
            status=self.status,
            status_text=self.status_text,
            beatmap_md5=self.beatmap_md5,
            mods=self.mods,
            play_mode=play_mode,
            beatmap_id=self.beatmap_id,
        )


DEFAULT_STABLE_USER_STATUS = StableUserStatus(
    status=StableStatus.Idle.value,
    status_text="",
    beatmap_md5="",
    mods=0,
    play_mode=0,
    beatmap_id=0,
)


__all__ = ["DEFAULT_STABLE_USER_STATUS", "StableStatus", "StableUserStatus"]
