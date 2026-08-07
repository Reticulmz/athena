"""Identity context の volatile session と authorization snapshot を定義する module."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.identity.authorization import Privileges


@dataclass(slots=True)
class SessionData:
    """Active session store へ保存する user と client の mutable state を表す value object.

    Attributes:
        user_id (int): session を所有する user ID.
        username (str): session 作成時の表示 user name.
        privileges (int): session 作成時の server-side privilege bitmask.
        country (str): user の country code.
        osu_version (str): login client が申告した osu! version.
        utc_offset (int): login client が申告した UTC offset.
        display_city (bool): city 表示を許可する client setting.
        client_hashes (str): client が送る fingerprint/hash 群の文字列表現.
        pm_private (bool): private message の受信設定.
        role_ids (tuple[int, ...]): session 作成時の privilege 計算元 role ID 群.
        silence_end (int): silence 状態の終了値. silence がない場合は0.
    """

    user_id: int
    username: str
    privileges: int
    country: str
    osu_version: str
    utc_offset: int
    display_city: bool
    client_hashes: str
    pm_private: bool
    role_ids: tuple[int, ...] = ()
    silence_end: int = 0

    def __post_init__(self) -> None:
        """Role ID collection を serializable な tuple へ正規化する.

        Returns:
            None: role_ids を置換するだけで値を返さない.

        Notes:
            Runtime では iterable が渡されても tuple に正規化される.
        """
        self.role_ids = tuple(self.role_ids)


@dataclass(slots=True, frozen=True)
class SessionAuthorization:
    """同じ role list から計算した immutable authorization snapshot を表す value object.

    Attributes:
        privileges (Privileges): snapshot 作成時に計算した privilege bit flag の組合せ.
        role_ids (tuple[int, ...]): privileges の計算元になった role ID 群.

    Notes:
        privileges と role_ids は同じ時点の role list から導出される一貫した組である.
    """

    privileges: Privileges
    role_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Role ID collection を immutable tuple へ正規化する.

        Returns:
            None: frozen instance の role_ids を正規化して値を返さない.
        """
        object.__setattr__(self, "role_ids", tuple(self.role_ids))


class AuthorizationRefreshStatus(StrEnum):
    """Session authorization refresh operation の outcome を表す enum.

    Attributes:
        REFRESHED (AuthorizationRefreshStatus): active session の authorization を更新した結果.
        NO_ACTIVE_SESSION (AuthorizationRefreshStatus): 更新対象の active session がない結果.
        FAILED (AuthorizationRefreshStatus): authorization の計算または更新に失敗した結果.
    """

    REFRESHED = "refreshed"
    NO_ACTIVE_SESSION = "no_active_session"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class UserAuthorizationRefreshResult:
    """単一 user の authorization refresh 結果を表す immutable value object.

    Attributes:
        user_id (int): refresh を試みた user ID.
        status (AuthorizationRefreshStatus): refresh operation の outcome.
        authorization (SessionAuthorization | None): REFRESHED 時の新しい snapshot.
            それ以外の status ではNone.

    Notes:
        authorization は status が REFRESHED の場合にだけ存在しなければならない.
    """

    user_id: int
    status: AuthorizationRefreshStatus
    authorization: SessionAuthorization | None = None

    def __post_init__(self) -> None:
        """Status と authorization の組合せが result invariant を満たすか検証する.

        Returns:
            None: validation だけを行い値を返さない.

        Raises:
            ValueError: REFRESHED に authorization がないか, 他 status に authorization がある場合.
        """
        if self.status == AuthorizationRefreshStatus.REFRESHED:
            if self.authorization is None:
                raise ValueError("authorization must be present when status is REFRESHED")
        elif self.authorization is not None:
            raise ValueError("authorization must be None when status is not REFRESHED")


@dataclass(slots=True, frozen=True)
class RoleAuthorizationRefreshResult:
    """Role に割り当てられた全 user の authorization refresh 結果を集約する value object.

    Attributes:
        role_id (int): refresh の起点になった role ID.
        user_results (tuple[UserAuthorizationRefreshResult, ...]): role に割り当てられた
            user ごとの結果.

    Notes:
        user_results は role assignment query が返した user ごとに一件ずつ持つ.
    """

    role_id: int
    user_results: tuple[UserAuthorizationRefreshResult, ...]

    def __post_init__(self) -> None:
        """User result collection を immutable tuple へ正規化する.

        Returns:
            None: frozen instance の user_results を正規化して値を返さない.
        """
        object.__setattr__(self, "user_results", tuple(self.user_results))
