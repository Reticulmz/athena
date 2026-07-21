"""score の canonical domain model と関連する列挙値を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import BeatmapRankStatus
    from osu_server.domain.scores.mods import ModCombination


class Ruleset(Enum):
    """score の ruleset を表す固定数値を定義する.

    Attributes:
        OSU (Ruleset): `OSU` を表す固定数値 0.
        TAIKO (Ruleset): `TAIKO` を表す固定数値 1.
        CATCH (Ruleset): `CATCH` を表す固定数値 2.
        MANIA (Ruleset): `MANIA` を表す固定数値 3.
    """

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3


class Playstyle(Enum):
    """score の playstyle を表す閉じた値集合を定義する.

    Attributes:
        VANILLA (Playstyle): `VANILLA` を表す固定数値 0.

    Notes:
        現在の domain scope では VANILLA だけを定義する.
    """

    VANILLA = 0


class Grade(Enum):
    """score result の grade 文字列値を定義する.

    Attributes:
        XH (Grade): grade 文字列 `XH`.
        X (Grade): grade 文字列 `X`.
        SH (Grade): grade 文字列 `SH`.
        S (Grade): grade 文字列 `S`.
        A (Grade): grade 文字列 `A`.
        B (Grade): grade 文字列 `B`.
        C (Grade): grade 文字列 `C`.
        D (Grade): grade 文字列 `D`.
    """

    XH = "XH"
    X = "X"
    SH = "SH"
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class PlayTimeSource(Enum):
    """submit 時点の play time 推定元を表す.

    Attributes:
        FAIL_TIME (PlayTimeSource): `fail_time` を値とする submit-time 推定元.
        BEATMAP_TOTAL_LENGTH (PlayTimeSource): `beatmap_total_length` を表す推定元.
    """

    FAIL_TIME = "fail_time"
    BEATMAP_TOTAL_LENGTH = "beatmap_total_length"


@dataclass(slots=True)
class Score:
    """受理済み play attempt と submit 時点の付帯情報を表す.

    Attributes:
        id (int | None): 永続化後の score ID. 未永続化時は None.
        user_id (int): score を送信した user の ID.
        beatmap_id (int): play した beatmap の ID.
        beatmap_checksum (str): submit 時点の beatmap checksum.
        online_checksum (str): online score を識別する checksum.
        ruleset (Ruleset): play に適用した ruleset.
        playstyle (Playstyle): play に適用した playstyle.
        mods (ModCombination): canonical な mod 組み合わせ.
        n300 (int): 300 判定数.
        n100 (int): 100 判定数.
        n50 (int): 50 判定数.
        geki (int): geki 判定数.
        katu (int): katu 判定数.
        miss (int): miss 判定数.
        score (int): client が送信した score 値.
        max_combo (int): play 中の最大 combo.
        accuracy (float): score validation が求めた accuracy ratio.
        grade (Grade): score validation が求めた grade.
        passed (bool): play が通過した場合は True.
        perfect (bool): client が perfect と報告した場合は True.
        client_version (str): score を送信した client version.
        submitted_at (datetime): server が受理した score の送信日時.
        beatmap_status_at_submission (BeatmapRankStatus | None): submit 時点の beatmap status.
        leaderboard_eligible_at_submission (bool): submit 時点で leaderboard 対象なら True.
        fail_time_ms (int | None): fail した時刻の millisecond 値. 不明時は None.
        play_time_seconds (int | None): 推定または確定した play time の秒数. 不明時は None.
        play_time_source (PlayTimeSource | None): play_time_seconds の推定元. 不明時は None.
        submit_exit_classification (str | None): score submit workflow の終了理由. 未分類時は None.
        replay_view_count (int): replay を閲覧した回数.

    Notes:
        この dataclass は timing 値と replay_view_count だけを検証する. timing source、
        hit count、accuracy、ほかの ID の相互整合性はここでは検証しない.
    """

    id: int | None
    user_id: int
    beatmap_id: int
    beatmap_checksum: str
    online_checksum: str
    ruleset: Ruleset
    playstyle: Playstyle
    mods: ModCombination
    n300: int
    n100: int
    n50: int
    geki: int
    katu: int
    miss: int
    score: int
    max_combo: int
    accuracy: float
    grade: Grade
    passed: bool
    perfect: bool
    client_version: str
    submitted_at: datetime
    beatmap_status_at_submission: BeatmapRankStatus | None = None
    leaderboard_eligible_at_submission: bool = False
    fail_time_ms: int | None = None
    play_time_seconds: int | None = None
    play_time_source: PlayTimeSource | None = None
    submit_exit_classification: str | None = None
    replay_view_count: int = 0

    def __post_init__(self) -> None:
        """Timing と replay 閲覧回数の最小 domain invariant を検証する.

        Returns:
            None: 検証が成功したことを示す. 値の変換は行わない.

        Raises:
            TypeError: replay_view_count が int instance ではない場合.
            ValueError: timing 値または replay_view_count が許容範囲外の場合.
        """
        _validate_non_negative_timing("fail_time_ms", self.fail_time_ms)
        _validate_non_negative_timing("play_time_seconds", self.play_time_seconds)
        _validate_replay_view_count(self.replay_view_count)


def _validate_non_negative_timing(field_name: str, value: int | None) -> None:
    """Optional timing 値が負でないことを検証する.

    Args:
        field_name (str): error message に使う timing field 名.
        value (int | None): 検証する timing 値. 不明を表す None は許容する.

    Returns:
        None: value が None または 0 以上であることを示す.

    Raises:
        ValueError: value が負の場合.
    """
    if value is not None and value < 0:
        msg = f"{field_name} must be non-negative"
        raise ValueError(msg)


def _validate_replay_view_count(value: object) -> None:
    """Replay 閲覧回数が null でない非負の int instance か検証する.

    Args:
        value (object): runtime で受け取った replay_view_count 値.

    Returns:
        None: value が許容される閲覧回数であることを示す.

    Raises:
        TypeError: value が int instance ではない場合.
        ValueError: value が None または負の場合.

    Notes:
        Python の `isinstance(value, int)` 判定を使うため bool は int instance として扱う.
    """
    if value is None:
        msg = "replay_view_count cannot be null"
        raise ValueError(msg)
    if not isinstance(value, int):
        msg = "replay_view_count must be an integer"
        raise TypeError(msg)
    if value < 0:
        msg = "replay_view_count must be non-negative"
        raise ValueError(msg)
