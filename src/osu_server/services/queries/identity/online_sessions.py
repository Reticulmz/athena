"""Online sessionのread-only query use-caseを定義するmodule.

active session storeからpresence表示に必要なsnapshotを取得する.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import SessionData
    from osu_server.repositories.interfaces.session_store import (
        ActiveSessionRoster,
        UserSessionLookup,
    )


@dataclass(slots=True, frozen=True)
class OnlineSessionSnapshot:
    """online presence表示に必要なsession fieldのread-only snapshotを表す.

    Attributes:
        user_id (int): online sessionを所有するuserの識別子.
        username (str): presenceへ表示するuser名.
        privileges (int): session作成時のserver-side privilege bitmask.
        country (str): presenceへ表示するcountry code.
        utc_offset (int): clientが申告したUTC offset.
    """

    user_id: int
    username: str
    privileges: int
    country: str
    utc_offset: int

    @classmethod
    def from_session(cls, session: SessionData) -> OnlineSessionSnapshot:
        """SessionDataからpresence表示用snapshotを作成する.

        Args:
            session (SessionData): active session storeから取得したsession data.

        Returns:
            OnlineSessionSnapshot: presence表示に必要なfieldだけを持つread-only snapshot.
        """
        return cls(
            user_id=session.user_id,
            username=session.username,
            privileges=session.privileges,
            country=session.country,
            utc_offset=session.utc_offset,
        )


@dataclass(slots=True, frozen=True)
class ListActiveSessionsQueryInput:
    """すべてのactive sessionを列挙する引数なしquery inputを表す."""


@dataclass(slots=True, frozen=True)
class ListActiveSessionsQueryResult:
    """active online session一覧のquery結果を表す.

    Attributes:
        sessions (tuple[OnlineSessionSnapshot, ...]): user ID昇順に並べたonline session snapshot群.
    """

    sessions: tuple[OnlineSessionSnapshot, ...]


@dataclass(slots=True, frozen=True)
class GetActiveSessionsByUserIdsQueryInput:
    """指定user IDのactive sessionだけを読むquery inputを表す.

    Attributes:
        user_ids (tuple[int, ...]): lookup順で照会するuser ID群. 重複は1回だけ照会する.
    """

    user_ids: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class GetActiveSessionsByUserIdsQueryResult:
    """指定user IDに対応するactive session snapshotのquery結果を表す.

    Attributes:
        sessions (tuple[OnlineSessionSnapshot, ...]): onlineだった指定userのsnapshot群.
    """

    sessions: tuple[OnlineSessionSnapshot, ...]


class ListActiveSessionsQuery(Protocol):
    """すべてのactive session snapshotを列挙するquery protocolを表す."""

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        """Active session snapshot一覧を返す.

        Args:
            input_data (ListActiveSessionsQueryInput): 引数なしのactive session一覧query input.

        Returns:
            ListActiveSessionsQueryResult: user ID昇順のactive session snapshot群を含む結果.
        """
        ...


class GetActiveSessionsByUserIdsQuery(Protocol):
    """指定user ID群のactive session snapshotを取得するquery protocolを表す."""

    async def execute(
        self,
        input_data: GetActiveSessionsByUserIdsQueryInput,
    ) -> GetActiveSessionsByUserIdsQueryResult:
        """指定user ID群に対応するactive session snapshotを返す.

        Args:
            input_data (GetActiveSessionsByUserIdsQueryInput): lookup順のuser ID群を指定するinput.

        Returns:
            GetActiveSessionsByUserIdsQueryResult: onlineだった指定userのsnapshot群を含む結果.
        """
        ...


class ListActiveSessionsQueryUseCase:
    """すべてのactive online session snapshotを読むquery use-caseを表す.

    Attributes:
        _session_store (ActiveSessionRoster): active session全件を列挙するvolatile state store.
    """

    _session_store: ActiveSessionRoster

    def __init__(self, *, session_store: ActiveSessionRoster) -> None:
        """Active session rosterを設定する.

        Args:
            session_store (ActiveSessionRoster): active session全件を列挙するstore.
        """
        self._session_store = session_store

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        """Active sessionをuser ID昇順のsnapshot一覧として取得する.

        Args:
            input_data (ListActiveSessionsQueryInput): 引数なしのactive session一覧query input.

        Returns:
            ListActiveSessionsQueryResult: user ID昇順のactive session snapshot群を含む結果.
        """
        _ = input_data
        sessions = await self._session_store.list_active_sessions()
        snapshots = tuple(
            sorted(
                (OnlineSessionSnapshot.from_session(session) for session in sessions),
                key=lambda snapshot: snapshot.user_id,
            )
        )
        return ListActiveSessionsQueryResult(sessions=snapshots)


class GetActiveSessionsByUserIdsQueryUseCase:
    """指定user ID群のactive online session snapshotを読むquery use-caseを表す.

    Attributes:
        _session_store (UserSessionLookup): user IDからactive sessionを取得する
            volatile state store.
    """

    _session_store: UserSessionLookup

    def __init__(self, *, session_store: UserSessionLookup) -> None:
        """user単位のactive session lookup storeを設定する.

        Args:
            session_store (UserSessionLookup): user IDからactive sessionを取得するstore.
        """
        self._session_store = session_store

    async def execute(
        self,
        input_data: GetActiveSessionsByUserIdsQueryInput,
    ) -> GetActiveSessionsByUserIdsQueryResult:
        """指定順でonline userのsession snapshotを取得する.

        Args:
            input_data (GetActiveSessionsByUserIdsQueryInput): lookup順のuser ID群を指定するinput.

        Returns:
            GetActiveSessionsByUserIdsQueryResult: onlineだった指定userのsnapshot群を含む結果.

        Notes:
            input内の重複user IDは最初の出現だけを照会し, offline userは結果から除外する.
        """
        snapshots: list[OnlineSessionSnapshot] = []
        for user_id in dict.fromkeys(input_data.user_ids):
            session = await self._session_store.get_by_user(user_id)
            if session is not None:
                snapshots.append(OnlineSessionSnapshot.from_session(session))

        return GetActiveSessionsByUserIdsQueryResult(sessions=tuple(snapshots))


__all__ = [
    "GetActiveSessionsByUserIdsQuery",
    "GetActiveSessionsByUserIdsQueryInput",
    "GetActiveSessionsByUserIdsQueryResult",
    "GetActiveSessionsByUserIdsQueryUseCase",
    "ListActiveSessionsQuery",
    "ListActiveSessionsQueryInput",
    "ListActiveSessionsQueryResult",
    "ListActiveSessionsQueryUseCase",
    "OnlineSessionSnapshot",
]
