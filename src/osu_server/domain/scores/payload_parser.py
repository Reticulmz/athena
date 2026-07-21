"""score submission workflow で共有する payload 値を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.mods import ModCombination


class ParseError(Exception):
    """score payload を domain 値へ変換できない場合の例外を表す."""


@dataclass(frozen=True, slots=True)
class ParsedScore:
    """client family の payload を mapping した後の score 入力を表す.

    Attributes:
        user_id (int): score を送信した user の ID.
        username (str): payload に含まれる user 名.
        beatmap_checksum (str): 対象 beatmap の checksum.
        online_checksum (str): online score を識別する checksum.
        ruleset (int): client payload の ruleset 数値. 検証前の値を保持する.
        mods (ModCombination): canonical な mod 組み合わせ.
        n300 (int): 300 判定の件数.
        n100 (int): 100 判定の件数.
        n50 (int): 50 判定の件数.
        geki (int): geki 判定の件数.
        katu (int): katu 判定の件数.
        miss (int): miss 判定の件数.
        score (int): client が送信した score 値.
        max_combo (int): client が送信した最大 combo.
        perfect (bool): client が perfect と報告した場合は True.
        passed (bool): client が play を通過したと報告した場合は True.
        client_grade (str | None): client が送信した grade. 未送信時は None.
        client_submitted_at (str | None): client payload の送信時刻文字列. 未送信時は None.
        client_version (str | None): client version 文字列. 未送信時は None.
        client_checksum (str | None): client 固有の checksum. 未送信時は None.

    Notes:
        hit count、ruleset、grade の整合性は後段の validation が判定する.
    """

    user_id: int
    username: str
    beatmap_checksum: str
    online_checksum: str
    ruleset: int
    mods: ModCombination
    n300: int
    n100: int
    n50: int
    geki: int
    katu: int
    miss: int
    score: int
    max_combo: int
    perfect: bool
    passed: bool
    client_grade: str | None = None
    client_submitted_at: str | None = None
    client_version: str | None = None
    client_checksum: str | None = None


__all__ = ["ParseError", "ParsedScore"]
