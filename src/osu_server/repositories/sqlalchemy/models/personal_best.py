from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy Mapped requires runtime import

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import LEADERBOARD_CATEGORY_ENUM


class PersonalBestModel(Base):
    __tablename__: str = "personal_bests"
    __table_args__: tuple[Index, ...] = (
        Index(
            "idx_personal_bests_scope_unique",
            "user_id",
            "beatmap_id",
            "ruleset",
            "playstyle",
            "category",
            unique=True,
        ),
        Index("idx_personal_bests_score_id", "score_id"),
        Index("idx_personal_bests_beatmap_category", "beatmap_id", "category"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    beatmap_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    playstyle: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    category: Mapped[str] = mapped_column(LEADERBOARD_CATEGORY_ENUM, nullable=False)
    score_id: Mapped[int] = mapped_column(
        ForeignKey("scores.id", name="fk_personal_bests_score_id"),
        nullable=False,
    )
    ranking_value: Mapped[int] = mapped_column(Integer, nullable=False)
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
