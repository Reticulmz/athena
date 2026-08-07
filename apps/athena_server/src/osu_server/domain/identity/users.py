"""Identity context の persistent user model を定義する module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(slots=True, init=False)
class User:
    """Authentication と profile 情報を保持する persistent user を表す domain model.

    Attributes:
        id (int): 永続化された user ID. test fixture では0を許容する.
        username (str): user に表示する name.
        safe_username (str): 一意性判定用に正規化した user name.
        email (str): user の email address.
        password_hash (str): 認証に使う password hash.
        country (str): ISO 3166-1 alpha-2 country code.
        created_at (datetime): user 作成時刻.
        updated_at (datetime): user row の最終更新時刻.
        latest_activity_at (datetime): user-observable activity の最新時刻.
    """

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
        id: int,  # noqa: A002 - Domain field mirrors persisted/public user id name.
        username: str,
        safe_username: str,
        email: str,
        password_hash: str,
        country: str,
        created_at: datetime,
        updated_at: datetime,
        latest_activity_at: datetime | None = None,
    ) -> None:
        """User の persistent field を初期化する.

        Args:
            id (int): 永続化済み user ID. test/domain fixture では0を許容する.
            username (str): 表示用 user name.
            safe_username (str): 一意性判定用に正規化済みの user name.
            email (str): user の email address.
            password_hash (str): 認証用 password hash.
            country (str): ISO 3166-1 alpha-2 country code.
            created_at (datetime): user 作成時刻.
            updated_at (datetime): user row の最終更新時刻.
            latest_activity_at (datetime | None): user-observable activity の最新時刻.
                未指定時は created_at を使用する.

        Notes:
            latest_activity_at は updated_at ではなく replay download などの
            user-observable activity 専用 metadata として扱う.
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
        """User name を一意性判定用の safe username へ正規化する.

        Args:
            username (str): 表示用の入力 user name.

        Returns:
            str: lowercase 化し space を underscore に置換した user name.

        Notes:
            この変換は文字種 validation を行わず, 比較用表現だけを作る.
        """
        return username.lower().replace(" ", "_")
