"""User model for the identity bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(slots=True, init=False)
class User:
    id: int
    username: str
    safe_username: str
    email: str
    password_hash: str
    country: str
    created_at: datetime
    updated_at: datetime
    latest_activity_at: datetime

    def __init__(
        self,
        id: int,  # noqa: A002
        username: str,
        safe_username: str,
        email: str,
        password_hash: str,
        country: str,
        created_at: datetime,
        updated_at: datetime,
        latest_activity_at: datetime | None = None,
    ) -> None:
        """User を作成する。

        latest_activity_at が未指定の場合は created_at を初期 activity として使う。
        updated_at は行更新 metadata であり activity の代替にはしない。
        """
        self.id = id
        self.username = username
        self.safe_username = safe_username
        self.email = email
        self.password_hash = password_hash
        self.country = country
        self.created_at = created_at
        self.updated_at = updated_at
        self.latest_activity_at = (
            latest_activity_at if latest_activity_at is not None else created_at
        )

    @staticmethod
    def normalize_username(username: str) -> str:
        """Normalize username: lowercase + spaces to underscores."""
        return username.lower().replace(" ", "_")
