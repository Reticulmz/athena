"""テスト用の辞書ベース in-memory セッションストアを提供する.

永続ストアや TTL を使わず, token と User ID の対応および SessionData をプロセス内に
保持する.
"""

from __future__ import annotations

from dataclasses import replace

from osu_server.domain.identity.sessions import (
    SessionAuthorization,  # noqa: TC001
    SessionData,  # noqa: TC001
)


class InMemorySessionStore:
    """SessionStore Protocol の in-memory 実装.

    Attributes:
        _by_token (dict[str, SessionData]): token から SessionData を引く主索引.
        _user_to_token (dict[int, str]): User ID から現在の token を引く逆索引.
        _token_to_user (dict[str, int]): token から User ID を引く逆索引.

    Notes:
        単一スレッドのテスト環境向けであり, thread-safe ではない. TTL を持たないため,
        有効期限の更新は存在確認として扱う.
    """

    def __init__(self) -> None:
        """空の token/User ID 索引を初期化する.

        Returns:
            None: 新しい session state を持つ store を構築する.
        """
        self._by_token: dict[str, SessionData] = {}
        self._user_to_token: dict[int, str] = {}
        self._token_to_user: dict[str, int] = {}

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """User の現在の session を保存する.

        Args:
            user_id (int): session を所有する User ID.
            token (str): session を識別する token.
            data (SessionData): 保存する session data.

        Returns:
            None: session と両方向の索引を更新する.

        Notes:
            同じ User ID に既存 session がある場合は, その token と逆索引を先に削除する.
            data は複製せずに保存する.
        """
        old_token = self._user_to_token.get(user_id)
        if old_token is not None:
            _ = self._by_token.pop(old_token, None)
            _ = self._token_to_user.pop(old_token, None)

        self._by_token[token] = data
        self._user_to_token[user_id] = token
        self._token_to_user[token] = user_id

    async def get(self, token: str) -> SessionData | None:
        """Token に対応する SessionData の浅い複製を返す.

        Args:
            token (str): 取得する session の token.

        Returns:
            SessionData | None: 見つかった session data の複製. 存在しなければ None.
        """
        data = self._by_token.get(token)
        return replace(data) if data is not None else None

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """User ID に対応する SessionData の浅い複製を返す.

        Args:
            user_id (int): 取得する session の所有者 ID.

        Returns:
            SessionData | None: 見つかった session data の複製. 索引または data がなければ None.
        """
        token = self._user_to_token.get(user_id)
        if token is None:
            return None
        data = self._by_token.get(token)
        return replace(data) if data is not None else None

    async def delete(self, token: str) -> None:
        """Token に対応する保存済み session を削除する.

        Args:
            token (str): 削除する session の token.

        Returns:
            None: 見つかった session の主索引と逆索引を削除する.

        Notes:
            token が主索引に存在しない場合は state を変更しない.
        """
        data = self._by_token.pop(token, None)
        if data is not None:
            user_id = self._token_to_user.pop(token, None)
            if user_id is not None and self._user_to_token.get(user_id) == token:
                del self._user_to_token[user_id]

    async def exists(self, token: str) -> bool:
        """Token が主索引に存在するかを返す.

        Args:
            token (str): 確認する session の token.

        Returns:
            bool: token が保存済みなら True, それ以外は False.
        """
        return token in self._by_token

    async def refresh(self, token: str) -> bool:
        """Session の更新可否を TTL を変更せずに返す.

        Args:
            token (str): 更新対象として確認する session の token.

        Returns:
            bool: token が保存済みなら True, それ以外は False.

        Notes:
            この store は TTL を持たないため, state を変更せず存在確認だけを行う.
        """
        return token in self._by_token

    async def delete_by_user(self, user_id: int) -> None:
        """User ID に対応する session を削除する.

        Args:
            user_id (int): 削除する session の所有者 ID.

        Returns:
            None: 見つかった session の主索引と逆索引を削除する.

        Notes:
            User ID の索引がなければ何も変更しないため, 繰り返し呼び出しても安全である.
        """
        token = self._user_to_token.pop(user_id, None)
        if token is None:
            return
        _ = self._by_token.pop(token, None)
        _ = self._token_to_user.pop(token, None)

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """現在の session の authorization fields だけを置き換える.

        Args:
            user_id (int): 更新対象 session の所有者 ID.
            authorization (SessionAuthorization): 保存する privileges と role IDs.

        Returns:
            bool: session を更新した場合は True. 対象の session がなければ False.

        Raises:
            KeyError: User ID の token 索引はあるが, 主索引に対応する session がない場合.

        Notes:
            新しい session は作成せず, session は削除せず, authorization 以外の field は
            保持する. privileges は int に変換して保存する.
        """
        token = self._user_to_token.get(user_id)
        if token is None:
            return False

        session = self._by_token[token]
        self._by_token[token] = replace(
            session,
            privileges=int(authorization.privileges),
            role_ids=authorization.role_ids,
        )
        return True

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """現在の session の pm_private field だけを置き換える.

        Args:
            user_id (int): 更新対象 session の所有者 ID.
            enabled (bool): 保存する private message 受信設定.

        Returns:
            bool: session を更新した場合は True. 対象の session がなければ False.

        Raises:
            KeyError: User ID の token 索引はあるが, 主索引に対応する session がない場合.

        Notes:
            新しい session は作成せず, session は削除せず, pm_private 以外の field は保持する.
        """
        token = self._user_to_token.get(user_id)
        if token is None:
            return False

        session = self._by_token[token]
        self._by_token[token] = replace(session, pm_private=enabled)
        return True

    async def list_active_sessions(self) -> list[SessionData]:
        """保存済みの全 SessionData の浅い複製を返す.

        Returns:
            list[SessionData]: token 主索引に保存された各 session data の複製.

        Notes:
            返す list と各 SessionData は store の内部コンテナを共有しない.
        """
        return [replace(session) for session in self._by_token.values()]
