"""userごとのlegacy personal best projectionを保存するORM modelを定義する.

projectionのidentityはuserとbeatmapおよびruleset/playstyle/categoryの非NULL scopeで決まる.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy Mapped requires runtime import

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models.enum_types import LEADERBOARD_CATEGORY_ENUM


class PersonalBestModel(Base):
    """leaderboard categoryごとのuser personal best scoreを表す.

    Attributes:
        __tablename__ (str): 保存先のpersonal_bests table名.
        __table_args__ (tuple[Index, ...]): scope一意性と検索を支えるindex群.
        id (Mapped[int]): 自動採番するprojectionのprimary key.
        user_id (Mapped[int]): best scoreを保持するuserの識別子.
        beatmap_id (Mapped[int]): 対象beatmapの識別子.
        ruleset (Mapped[int]): 対象rulesetのcanonical integer値.
        playstyle (Mapped[int]): 対象playstyleのcanonical integer値.
        category (Mapped[str]): personal bestを分けるleaderboard category.
        score_id (Mapped[int]): projectionの根拠となるscoreのforeign key.
        ranking_value (Mapped[int]): category内の比較に使う順位値.
        created_at (Mapped[datetime]): projectionを作成したUTC timestamp.
        updated_at (Mapped[datetime]): projectionを最後に更新したUTC timestamp.
    """

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
