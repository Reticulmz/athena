"""current user statisticsとbeatmap performance bestを保存するORM modelを定義する.

両projectionはruleset/playstyleを非NULL scopeに含める.
rank queryに必要な値をread modelとして保持する.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- SQLAlchemy Mapped requires runtime import
from decimal import Decimal  # noqa: TC003 -- SQLAlchemy Mapped requires runtime import

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class BeatmapPerformanceBestModel(Base):
    """beatmapごとのuser最高performance scoreを表すprojection.

    Attributes:
        __tablename__ (str): 保存先のbeatmap_performance_bests table名.
        __table_args__ (tuple[CheckConstraint | Index, ...]):
            scope一意性とranking/rebuildを支えるconstraint/index.
        id (Mapped[int]): 自動採番するprojectionのprimary key.
        user_id (Mapped[int]): best performanceを保持するuserの識別子.
        beatmap_id (Mapped[int]): 対象beatmapの識別子.
        ruleset (Mapped[int]): 対象rulesetのcanonical integer値.
        playstyle (Mapped[int]): 対象playstyleのcanonical integer値.
        score_id (Mapped[int]): projectionの根拠となるscoreのforeign key.
        performance_calculation_id (Mapped[int]): 根拠となるperformance calculationのforeign key.
        pp (Mapped[Decimal]): rankingに使うperformance point. 負値は保存できない.
        accuracy (Mapped[float]): scoreのaccuracy ratio. 0から1までに制約される.
        score (Mapped[int]): score比較に使うscore値. 負値は保存できない.
        submitted_at (Mapped[datetime]): scoreを受理したUTC timestamp.
        created_at (Mapped[datetime]): projectionを作成したUTC timestamp.
        updated_at (Mapped[datetime]): projectionを最後に更新したUTC timestamp.
    """

    __tablename__: str = "beatmap_performance_bests"
    __table_args__: tuple[CheckConstraint | Index, ...] = (
        CheckConstraint("pp >= 0", name="ck_beatmap_performance_bests_pp_non_negative"),
        CheckConstraint(
            "accuracy >= 0 AND accuracy <= 1",
            name="ck_beatmap_performance_bests_accuracy_ratio",
        ),
        CheckConstraint("score >= 0", name="ck_beatmap_performance_bests_score_non_negative"),
        Index(
            "idx_beatmap_performance_bests_scope_unique",
            "user_id",
            "beatmap_id",
            "ruleset",
            "playstyle",
            unique=True,
        ),
        Index(
            "idx_beatmap_performance_bests_rank_support",
            "ruleset",
            "playstyle",
            text("pp DESC"),
            "user_id",
        ),
        Index(
            "idx_beatmap_performance_bests_user_rebuild",
            "user_id",
            "beatmap_id",
            "ruleset",
            "playstyle",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beatmap_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    playstyle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("scores.id", name="fk_beatmap_performance_bests_score_id"),
        nullable=False,
    )
    performance_calculation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "score_performance_calculations.id",
            name="fk_beatmap_performance_bests_performance_calculation_id",
        ),
        nullable=False,
    )
    pp: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CurrentUserStatsModel(Base):
    """userのruleset/playstyle別current statisticsを表すprojection.

    Attributes:
        __tablename__ (str): 保存先のcurrent_user_stats table名.
        __table_args__ (tuple[CheckConstraint | Index, ...]): 集計値制約とrank queryを支えるindex.
        user_id (Mapped[int]): statisticsを保持するuserの識別子かつ複合primary key要素.
        ruleset (Mapped[int]): 対象rulesetかつ複合primary key要素.
        playstyle (Mapped[int]): 対象playstyleかつ複合primary key要素.
        pp (Mapped[Decimal]): current performance point. 負値は保存できない.
        accuracy (Mapped[float]): current accuracy ratio. 0から1までに制約される.
        play_count (Mapped[int]): 集計対象play数. 負値は保存できない.
        ranked_score (Mapped[int]): ranked score合計. 負値は保存できない.
        total_score (Mapped[int]): total score合計. 負値は保存できない.
        max_combo (Mapped[int]): 観測済み最大combo. 負値は保存できない.
        play_time_seconds (Mapped[int | None]): 集計play時間秒数. 不明ならNULL.
        count_300 (Mapped[int]): 300 judgement累計. 負値は保存できない.
        count_100 (Mapped[int]): 100 judgement累計. 負値は保存できない.
        count_50 (Mapped[int]): 50 judgement累計. 負値は保存できない.
        count_geki (Mapped[int]): geki judgement累計. 負値は保存できない.
        count_katu (Mapped[int]): katu judgement累計. 負値は保存できない.
        count_miss (Mapped[int]): miss judgement累計. 負値は保存できない.
        created_at (Mapped[datetime]): projectionを作成したUTC timestamp.
        updated_at (Mapped[datetime]): projectionを最後に更新したUTC timestamp.
    """

    __tablename__: str = "current_user_stats"
    __table_args__: tuple[CheckConstraint | Index, ...] = (
        CheckConstraint("pp >= 0", name="ck_current_user_stats_pp_non_negative"),
        CheckConstraint(
            "accuracy >= 0 AND accuracy <= 1",
            name="ck_current_user_stats_accuracy_ratio",
        ),
        CheckConstraint("play_count >= 0", name="ck_current_user_stats_play_count_non_negative"),
        CheckConstraint(
            "ranked_score >= 0",
            name="ck_current_user_stats_ranked_score_non_negative",
        ),
        CheckConstraint(
            "total_score >= 0",
            name="ck_current_user_stats_total_score_non_negative",
        ),
        CheckConstraint("max_combo >= 0", name="ck_current_user_stats_max_combo_non_negative"),
        CheckConstraint(
            "play_time_seconds IS NULL OR play_time_seconds >= 0",
            name="ck_current_user_stats_play_time_seconds_non_negative",
        ),
        CheckConstraint("count_300 >= 0", name="ck_current_user_stats_count_300_non_negative"),
        CheckConstraint("count_100 >= 0", name="ck_current_user_stats_count_100_non_negative"),
        CheckConstraint("count_50 >= 0", name="ck_current_user_stats_count_50_non_negative"),
        CheckConstraint("count_geki >= 0", name="ck_current_user_stats_count_geki_non_negative"),
        CheckConstraint("count_katu >= 0", name="ck_current_user_stats_count_katu_non_negative"),
        CheckConstraint("count_miss >= 0", name="ck_current_user_stats_count_miss_non_negative"),
        Index(
            "idx_current_user_stats_rank_support",
            "ruleset",
            "playstyle",
            text("pp DESC"),
            "user_id",
        ),
    )

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ruleset: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    playstyle: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    pp: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    play_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ranked_score: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_score: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_combo: Mapped[int] = mapped_column(Integer, nullable=False)
    play_time_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    count_300: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count_100: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count_50: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count_geki: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count_katu: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count_miss: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
