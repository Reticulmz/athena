"""roleとuser role割当を保存するSQLAlchemy ORM modelを定義する.

roleの名前は一意である. user role割当はuserとroleの複合primary keyで重複を拒否する.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from osu_server.infrastructure.database.base import Base


class RoleModel(Base):
    """認可roleの名前と権限bitsetを保存する.

    Attributes:
        __tablename__ (str): 保存先のroles table名.
        id (Mapped[int]): 自動採番するroleのprimary key.
        name (Mapped[str]): 一意なrole名.
        permissions (Mapped[int]): roleが許可するPrivilegeのbitset.
        position (Mapped[int]): role一覧で使う並び順.
    """

    __tablename__: str = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    permissions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class UserRoleModel(Base):
    """userとroleの多対多割当を保存する.

    Attributes:
        __tablename__ (str): 保存先のuser_roles table名.
        user_id (Mapped[int]): 割当先userのprimary keyかつforeign key.
        role_id (Mapped[int]): 割り当てるroleのprimary keyかつforeign key.
    """

    __tablename__: str = "user_roles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
