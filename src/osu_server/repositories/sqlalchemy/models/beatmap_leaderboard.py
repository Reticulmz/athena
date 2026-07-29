"""beatmap leaderboard projectionを保存するSQLAlchemy ORM modelを定義する.

raw mod bitflagごとのuser best rowを保持する. global leaderboardはmodを横断して最高rowを選ぶ.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- SQLAlchemy Mapped requires runtime import

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    column,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class BeatmapLeaderboardUserBestModel(Base):
    """raw mod bitflagごとのuser最高scoreを保持するprojectionを表す.

    Attributes:
        __tablename__ (str): 保存先のbeatmap_leaderboard_user_bests table名.
        __table_args__ (tuple[CheckConstraint | Index | UniqueConstraint, ...]):
            scope一意性とranking indexおよびmod制約.
        id (Mapped[int]): 自動採番するprojection rowのprimary key.
        beatmap_id (Mapped[int]): 対象beatmapの識別子.
        beatmap_checksum (Mapped[str]): ranking時点のbeatmap checksum.
        ruleset (Mapped[int]): 対象rulesetのcanonical integer値.
        playstyle (Mapped[int]): 対象playstyleのcanonical integer値.
        user_id (Mapped[int]): best scoreを保持するuserの識別子.
        mods (Mapped[int]): raw mod bitflag. 負値は保存できない.
        score_id (Mapped[int]): projectionの根拠となるscoreのforeign key.
        score (Mapped[int]): leaderboard比較に使うscore値.
        submitted_at (Mapped[datetime]): scoreを受理したUTC timestamp.
        created_at (Mapped[datetime]): projection rowを作成したUTC timestamp.
        updated_at (Mapped[datetime]): projection rowを最後に更新したUTC timestamp.

    Notes:
        beatmap/ruleset/playstyle/user/modsのscopeごとに1 rowだけを保持する.
        global leaderboardはmodsを無視して各userの最高rowを選ぶ.
    """

    __tablename__: str = "beatmap_leaderboard_user_bests"
    __table_args__: tuple[CheckConstraint | Index | UniqueConstraint, ...] = (
        UniqueConstraint(
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            "mods",
            name="uq_beatmap_leaderboard_user_bests_scope",
        ),
        UniqueConstraint(
            "score_id",
            name="uq_beatmap_leaderboard_user_bests_score_id",
        ),
        CheckConstraint(
            column("mods", Integer) >= 0,
            name="ck_beatmap_leaderboard_user_bests_mods_non_negative",
        ),
        Index(
            "idx_beatmap_leaderboard_user_bests_user_rebuild",
            "user_id",
            "beatmap_id",
            "ruleset",
            "playstyle",
        ),
        Index(
            "idx_beatmap_leaderboard_user_bests_global_rank",
            "beatmap_id",
            "ruleset",
            "playstyle",
            "beatmap_checksum",
            "user_id",
            column("score", Integer).desc(),
            column("submitted_at", DateTime(timezone=True)).asc(),
            column("score_id", BigInteger).asc(),
        ),
        Index(
            "idx_beatmap_leaderboard_user_bests_mod_rank",
            "beatmap_id",
            "ruleset",
            "playstyle",
            "beatmap_checksum",
            "mods",
            "user_id",
            column("score", Integer).desc(),
            column("submitted_at", DateTime(timezone=True)).asc(),
            column("score_id", BigInteger).asc(),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    beatmap_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beatmap_checksum: Mapped[str] = mapped_column(String(32), nullable=False)
    ruleset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    playstyle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    mods: Mapped[int] = mapped_column(Integer, nullable=False)
    score_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("scores.id", name="fk_beatmap_leaderboard_user_bests_score_id"),
        nullable=False,
    )
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
