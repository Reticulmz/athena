"""揮発性 session state を扱う caller 向け Protocol を定義する.

この module の Protocol は durable command transaction を開始または所有しない.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from osu_server.domain.identity.sessions import (
    SessionAuthorization,  # noqa: TC001  # runtime_checkable needs runtime access
    SessionData,  # noqa: TC001  # runtime_checkable needs runtime access
)


@runtime_checkable
class LoginSessionWriter(Protocol):
    """成功した login 用に揮発性 session を保存する capability を定義する.

    Notes:
        この Protocol は session store の更新だけを扱う. Command Unit of Work への参加や
        commit/rollback は行わない.
    """

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """User の active session を保存し既存 session を置き換える.

        Args:
            user_id (int): Session を所有する User ID.
            token (str): Session を一意に参照する token.
            data (SessionData): 保存する session snapshot.

        Returns:
            None: Session store への保存完了を表す.

        Notes:
            同じ User に既存 session がある場合は新しい token の session に置き換える.
            永続化 transaction の commit/rollback はこの operation に含まれない.
        """
        ...


@runtime_checkable
class PollingSessionRuntime(Protocol):
    """Stable polling で使う session 読み取りと TTL 更新を定義する.

    Notes:
        `get()` は読み取りだけを行う. `refresh()` は揮発性 session の寿命だけを更新し
        durable state を変更しない.
    """

    async def get(self, token: str) -> SessionData | None:
        """Token に対応する session data を返す.

        Args:
            token (str): 検索する session token.

        Returns:
            SessionData | None: Active session の snapshot. Token が存在しない場合は `None`.

        Notes:
            この読み取りは Command Unit of Work を開始せず commit/rollback もしない.
        """
        ...

    async def refresh(self, token: str) -> bool:
        """Token に対応する active session の TTL を更新する.

        Args:
            token (str): 更新する session token.

        Returns:
            bool: Session が存在し TTL を更新できた場合は `True`. 存在しない場合は `False`.

        Notes:
            TTL を持たない実装では existence check と同じ結果になり得る. Durable command
            transaction の commit/rollback は行わない.
        """
        ...


@runtime_checkable
class UserSessionLookup(Protocol):
    """User 指定の online check 用 session 読み取りを定義する."""

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """User に対応する active session data を返す.

        Args:
            user_id (int): 検索する User ID.

        Returns:
            SessionData | None: Active session の snapshot. Session がない場合は `None`.

        Notes:
            この読み取りは durable persistence transaction を所有しない.
        """
        ...


@runtime_checkable
class SessionLifecycleRuntime(Protocol):
    """Disconnect handling 用の session lifecycle operation を定義する.

    Notes:
        Operation は volatile session state だけを変更する. Command Unit of Work の
        durable mutation と atomic に組み合わせる責務は caller にある.
    """

    async def delete(self, token: str) -> None:
        """Token で識別する session を削除する.

        Args:
            token (str): 削除する session token.

        Returns:
            None: Session が削除済みまたは存在しないことを表す.

        Notes:
            実装は token と User の reverse mapping を整合させる. Durable transaction の
            rollback によってこの操作を取り消すことはできない.
        """
        ...

    async def exists(self, token: str) -> bool:
        """Token に対応する active session の有無を返す.

        Args:
            token (str): 確認する session token.

        Returns:
            bool: Active session が存在する場合は `True`. 存在しない場合は `False`.

        Notes:
            この operation は volatile state の読み取りだけを行い transaction を所有しない.
        """
        ...

    async def delete_by_user(self, user_id: int) -> None:
        """User に対応する active session を削除する.

        Args:
            user_id (int): 削除する session の所有者 User ID.

        Returns:
            None: 対象 session が削除済みまたは存在しないことを表す.

        Notes:
            Session が存在しない場合は no-op であり idempotent である. Durable command
            transaction の commit/rollback は行わない.
        """
        ...


@runtime_checkable
class SessionAuthorizationRuntime(Protocol):
    """Active session の authorization snapshot 更新を定義する."""

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """Active session の privileges と role_ids だけを更新する.

        Args:
            user_id (int): 更新対象 session の所有者 User ID.
            authorization (SessionAuthorization): 保存する authorization snapshot.

        Returns:
            bool: Active session を更新した場合は `True`. Session がない場合は `False`.

        Notes:
            新規 session の作成や削除は行わず authorization 以外の field は変更しない.
            この volatile update は Command Unit of Work の transaction に参加しない.
        """
        ...


@runtime_checkable
class SessionPrivacyRuntime(Protocol):
    """Active session の private-message privacy 更新を定義する."""

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """Active session の pm_private だけを更新する.

        Args:
            user_id (int): 更新対象 session の所有者 User ID.
            enabled (bool): Private message を private にする場合は `True`.

        Returns:
            bool: Active session を更新した場合は `True`. Session がない場合は `False`.

        Notes:
            新規 session の作成や削除は行わず privacy 以外の field は変更しない.
            Durable command transaction の commit/rollback は行わない.
        """
        ...


@runtime_checkable
class ActiveSessionRoster(Protocol):
    """Stable online roster 用の active session 一覧読み取りを定義する."""

    async def list_active_sessions(self) -> list[SessionData]:
        """現在 active なすべての session data を返す.

        Returns:
            list[SessionData]: 読み取り時点で active な session snapshot の一覧.

        Notes:
            空の store では空の list を返す. この読み取りは durable transaction を開始または
            所有しない.
        """
        ...


@runtime_checkable
class SessionStore(
    LoginSessionWriter,
    PollingSessionRuntime,
    UserSessionLookup,
    SessionLifecycleRuntime,
    SessionAuthorizationRuntime,
    SessionPrivacyRuntime,
    ActiveSessionRoster,
    Protocol,
):
    """Valkey または memory store が実装する完全な session storage interface を定義する.

    Notes:
        この aggregate Protocol は session の volatile lifecycle と lookup を集約する.
        Query repository の read-only contract と異なり session mutation を含むが durable
        persistence transaction を開始または所有しない. Command Unit of Work の commit/rollback
        と session update の順序を決める責務は use-case 側にある.
    """


__all__ = [
    "ActiveSessionRoster",
    "LoginSessionWriter",
    "PollingSessionRuntime",
    "SessionAuthorizationRuntime",
    "SessionLifecycleRuntime",
    "SessionPrivacyRuntime",
    "SessionStore",
    "UserSessionLookup",
]
