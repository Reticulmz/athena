from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- SQLAlchemy Mapped requires runtime import

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class BeatmapLeaderboardUserBestModel(Base):
    """Global all-mods のユーザー最高 score を保持する ORM model.

    Notes:
        1ユーザーにつき Beatmap/ruleset/playstyle ごとに1行だけ保持する. score_id も一意で、
        Selected Mods 用の scope 行は保存しない.
    """

    __tablename__: str = "beatmap_leaderboard_user_bests"
    __table_args__: tuple[Index | UniqueConstraint, ...] = (
        UniqueConstraint(
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            name="uq_beatmap_leaderboard_user_bests_scope",
        ),
        UniqueConstraint(
            "score_id",
            name="uq_beatmap_leaderboard_user_bests_score_id",
        ),
        Index(
            "idx_beatmap_leaderboard_user_bests_user_rebuild",
            "user_id",
            "beatmap_id",
            "ruleset",
            "playstyle",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    beatmap_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beatmap_checksum: Mapped[str] = mapped_column(String(32), nullable=False)
    ruleset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    playstyle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
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
