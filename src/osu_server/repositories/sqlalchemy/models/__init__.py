"""SQLAlchemy ORM models.

Import all models here so that Alembic can discover them via Base.metadata.
"""

from osu_server.repositories.sqlalchemy.models.channel import ChannelModel
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.user import (
    DisallowedUsernameModel,
    UserModel,
)

__all__ = [
    "ChannelModel",
    "DisallowedUsernameModel",
    "RoleModel",
    "UserModel",
    "UserRoleModel",
]
