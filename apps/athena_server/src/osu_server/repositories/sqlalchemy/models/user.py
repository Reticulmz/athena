"""user identityと登録禁止usernameを保存するSQLAlchemy ORM modelを定義する.

login lookupにはsafe_usernameを使う. emailとsafe_usernameの一意性はdatabaseで保証する.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — SQLAlchemy Mapped requires runtime import

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class UserModel(Base):
    """認証とprofileの最小user recordを表す.

    Attributes:
        __tablename__ (str): 保存先のusers table名.
        id (Mapped[int]): 自動採番するuserのprimary key.
        username (Mapped[str]): 表示用のusername.
        safe_username (Mapped[str]): 正規化済みで一意なlogin lookup用username.
        email (Mapped[str]): 一意な連絡先email address.
        password_hash (Mapped[str]): hash化済みpassword credential.
        country (Mapped[str]): ISO 3166-1 alpha-2 country code.
        created_at (Mapped[datetime]): userを作成したUTC timestamp.
        updated_at (Mapped[datetime]): user recordを最後に更新したUTC timestamp.
        latest_activity_at (Mapped[datetime]): 最後に観測したuser activityのUTC timestamp.
    """

    __tablename__: str = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(15), nullable=False)
    safe_username: Mapped[str] = mapped_column(String(15), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, server_default="XX")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    latest_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DisallowedUsernameModel(Base):
    """registrationで拒否する正規化済みusernameを表す.

    Attributes:
        __tablename__ (str): 保存先のdisallowed_usernames table名.
        id (Mapped[int]): 自動採番する禁止username recordのprimary key.
        safe_username (Mapped[str]): 一意な正規化済み禁止username.
        created_at (Mapped[datetime]): recordを作成したUTC timestamp.
    """

    __tablename__: str = "disallowed_usernames"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    safe_username: Mapped[str] = mapped_column(String(15), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
