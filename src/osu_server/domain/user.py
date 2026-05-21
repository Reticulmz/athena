from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(slots=True)
class User:
    id: int
    username: str
    safe_username: str
    email: str
    password_hash: str
    country: str
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def normalize_username(username: str) -> str:
        """Normalize username: lowercase + spaces to underscores."""
        return username.lower().replace(" ", "_")
