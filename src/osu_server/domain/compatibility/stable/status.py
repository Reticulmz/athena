"""Stable client status の compatibility value を定義する module."""

from dataclasses import dataclass
from enum import IntEnum


class StableStatus(IntEnum):
    """Stable client の Status wire 値を表す enum.

    Attributes:
        Idle (StableStatus): idle status の wire 値0.
        Afk (StableStatus): away-from-keyboard status の wire 値1.
        Playing (StableStatus): playing status の wire 値2.
        Editing (StableStatus): editing status の wire 値3.
        Modding (StableStatus): modding status の wire 値4.
        Multiplayer (StableStatus): multiplayer status の wire 値5.
        Watching (StableStatus): watching status の wire 値6.
        Unknown (StableStatus): unknown status の wire 値7.
        Testing (StableStatus): testing status の wire 値8.
        Submitting (StableStatus): submitting status の wire 値9.
        Paused (StableStatus): paused status の wire 値10.
        Lobby (StableStatus): lobby status の wire 値11.
        Multiplaying (StableStatus): multiplaying status の wire 値12.
        OsuDirect (StableStatus): osu!direct status の wire 値13.
    """

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
    """Stable USER_STATS に載せる current status field を表す immutable value object.

    Attributes:
        status (int): Stable Status の wire 値.
        status_text (str): client が送った status text.
        beatmap_md5 (str): client が送った beatmap MD5. 未設定時は空文字.
        mods (int): Stable mod bitmask.
        play_mode (int): Stable Mode の wire 値.
        beatmap_id (int): client が送った beatmap ID. 未設定時は0.

    Notes:
        Bancho wire 型ではなく, transport から domain-compatible state へ写した値として扱う.
    """

    status: int
    status_text: str
    beatmap_md5: str
    mods: int
    play_mode: int
    beatmap_id: int

    def with_play_mode(self, play_mode: int) -> "StableUserStatus":
        """Play mode だけを差し替えた current status を返す.

        Args:
            play_mode (int): 置き換える Stable Mode wire 値.

        Returns:
            StableUserStatus: 他の field を保持して play_mode だけを置き換えた value object.
        """
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
