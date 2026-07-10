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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class BeatmapLeaderboardUserBestModel(Base):
    __tablename__: str = "beatmap_leaderboard_user_bests"
    __table_args__: tuple[CheckConstraint | Index, ...] = (
        CheckConstraint(
            "mod_filter_key >= -1",
            name="ck_beatmap_leaderboard_user_bests_mod_filter_key_scope",
        ),
        Index(
            "idx_beatmap_leaderboard_user_bests_scope_unique",
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            "mod_filter_key",
            unique=True,
        ),
        Index(
            "idx_beatmap_leaderboard_user_bests_ordering",
            "beatmap_id",
            "ruleset",
            "playstyle",
            "mod_filter_key",
            text("score DESC"),
            text("submitted_at ASC"),
            text("score_id ASC"),
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
    ruleset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    playstyle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    mod_filter_key: Mapped[int] = mapped_column(Integer, nullable=False)
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
