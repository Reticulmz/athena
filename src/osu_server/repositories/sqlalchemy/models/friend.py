"""user間のfriend relationshipを保存するSQLAlchemy ORM modelを定義する.

同一userをownerとtargetにするrelationshipはCHECK constraintで拒否する.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - SQLAlchemy Mapped requires runtime import

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class UserFriendRelationshipModel(Base):
    """owner userが登録したfriend relationshipを表す.

    Attributes:
        __tablename__ (str): 保存先のuser_friend_relationships table名.
        __table_args__ (tuple[CheckConstraint, ...]): self relationshipを拒否するconstraint.
        owner_user_id (Mapped[int]): friend一覧を所有するuserのforeign key.
        target_user_id (Mapped[int]): friendとして登録されたuserのforeign key.
        created_at (Mapped[datetime]): relationshipを作成したUTC timestamp.
    """

    __tablename__: str = "user_friend_relationships"
    __table_args__: tuple[CheckConstraint, ...] = (
        CheckConstraint(
            "owner_user_id <> target_user_id",
            name="ck_user_friend_relationships_no_self",
        ),
    )

    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_user_friend_relationships_owner_user_id",
        ),
        primary_key=True,
    )
    target_user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_user_friend_relationships_target_user_id",
        ),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
