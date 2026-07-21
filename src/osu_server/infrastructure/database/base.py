"""SQLAlchemy ORM model用のdeclarative baseを定義するmodule.

全ORM modelは``Base``を継承し, Alembicがschema変更を検出できるようにする.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全SQLAlchemy ORM modelが継承するdeclarative base.

    Attributes:
        なし: SQLAlchemyが継承先modelのmetadataを管理する.
    """
