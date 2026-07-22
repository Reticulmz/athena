"""Valkeyをbacking storeにするstable session repositoryを実装する.

session tokenとuser reverse mappingをTTL付きkeyとして保存する.
Lua scriptで複数keyの更新をatomicにする.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, ClassVar

from glide import Script

from osu_server.domain.identity.sessions import (
    SessionAuthorization,  # runtime use via invoke_script args
    SessionData,
)

if TYPE_CHECKING:
    from glide import GlideClient


class ValkeySessionStore:
    """Valkey上でSessionStore Protocolを実装するrepositoryを表す.

    Attributes:
        _CREATE_SCRIPT (ClassVar[Script]): old session削除と新session作成をatomicにするLua script.
        _REFRESH_SCRIPT (ClassVar[Script]): sessionとuser mappingのTTLをatomicに更新するLua script.
        _DELETE_BY_USER_SCRIPT (ClassVar[Script]):
            user reverse mappingからsessionをatomicに削除するLua script.
        _UPDATE_AUTHORIZATION_SCRIPT (ClassVar[Script]):
            active sessionのauthorization snapshotをatomicに置換するLua script.
        _UPDATE_PM_PRIVATE_SCRIPT (ClassVar[Script]):
            active sessionのpm_private flagをatomicに置換するLua script.
        _DELETE_SCRIPT (ClassVar[Script]):
            token sessionと一致するuser reverse mappingをatomicに削除するLua script.
        _client (GlideClient): Valkey commandとLua scriptを実行するclient.
        _ttl (int): create/refreshでsession keyへ設定するTTL秒数.
        _prefix (str): 全session keyのnamespaceを分離するprefix.

    Notes:
        session keyは{prefix}session:{token}を使う.
        user reverse mappingは{prefix}user_session:{user_id}を使う.
        create/delete/refreshと各patchはLua scriptで実行する.
        read-modify-writeのTOCTOU raceを避ける.
        createは同一userのold tokenを先に削除する. session keyとreverse mappingへ同じTTLを設定する.
    """

    # KEYS[1] = user_session:{user_id}, KEYS[2] = session:{new_token}
    # ARGV[1] = session key prefix, ARGV[2] = JSON data, ARGV[3] = TTL, ARGV[4] = token
    _CREATE_SCRIPT: ClassVar[Script] = Script("""\
local old_token = redis.call('GET', KEYS[1])
if old_token then
    redis.call('DEL', ARGV[1] .. old_token)
end
redis.call('SET', KEYS[2], ARGV[2], 'EX', tonumber(ARGV[3]))
redis.call('SET', KEYS[1], ARGV[4], 'EX', tonumber(ARGV[3]))
return 1""")

    # KEYS[1] = session:{token}
    # ARGV[1] = TTL, ARGV[2] = user_id JSON field name, ARGV[3] = user key prefix
    _REFRESH_SCRIPT: ClassVar[Script] = Script("""\
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
local data = cjson.decode(raw)
local user_id = data[ARGV[2]]
if user_id ~= nil then
    local user_key = ARGV[3] .. tostring(math.floor(user_id))
    redis.call('EXPIRE', user_key, tonumber(ARGV[1]))
end
return 1""")

    # KEYS[1] = user_session:{user_id}
    # ARGV[1] = session key prefix
    _DELETE_BY_USER_SCRIPT: ClassVar[Script] = Script("""\
local token = redis.call('GET', KEYS[1])
if not token then
    return 0
end
redis.call('DEL', ARGV[1] .. token)
redis.call('DEL', KEYS[1])
return 1""")

    # KEYS[1] = user_session:{user_id}
    # ARGV[1] = session key prefix
    # ARGV[2] = new privileges (int as string)
    # ARGV[3] = new role_ids (JSON array string)
    _UPDATE_AUTHORIZATION_SCRIPT: ClassVar[Script] = Script("""\
local token = redis.call('GET', KEYS[1])
if not token then
    return 0
end
local session_key = ARGV[1] .. token
local raw = redis.call('GET', session_key)
if not raw then
    return 0
end
local ttl = redis.call('TTL', session_key)
if ttl <= 0 then
    ttl = 3600
end
local data = cjson.decode(raw)
data['privileges'] = tonumber(ARGV[2])
data['role_ids'] = cjson.decode(ARGV[3])
redis.call('SET', session_key, cjson.encode(data), 'EX', ttl)
return 1""")

    # KEYS[1] = user_session:{user_id}
    # ARGV[1] = session key prefix
    # ARGV[2] = enabled flag ("1" or "0")
    _UPDATE_PM_PRIVATE_SCRIPT: ClassVar[Script] = Script("""\
local token = redis.call('GET', KEYS[1])
if not token then
    return 0
end
local session_key = ARGV[1] .. token
local raw = redis.call('GET', session_key)
if not raw then
    return 0
end
local pttl = redis.call('PTTL', session_key)
if pttl == -2 then
    return 0
end
local data = cjson.decode(raw)
data['pm_private'] = ARGV[2] == '1'
local encoded = cjson.encode(data)
if pttl == -1 then
    redis.call('SET', session_key, encoded)
    return 1
end
if pttl < 1 then
    pttl = 1
end
redis.call('SET', session_key, encoded, 'PX', pttl)
return 1""")

    # KEYS[1] = session:{token}
    # ARGV[1] = user_id JSON field name, ARGV[2] = user key prefix, ARGV[3] = token
    _DELETE_SCRIPT: ClassVar[Script] = Script("""\
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
local data = cjson.decode(raw)
local user_id = data[ARGV[1]]
if user_id ~= nil then
    local user_key = ARGV[2] .. tostring(math.floor(user_id))
    local current_token = redis.call('GET', user_key)
    if current_token == ARGV[3] then
        redis.call('DEL', user_key)
    end
end
redis.call('DEL', KEYS[1])
return 1""")

    def __init__(
        self,
        client: GlideClient,
        *,
        ttl: int = 3600,
        key_prefix: str = "",
    ) -> None:
        """Valkey clientとsession keyの有効期限設定を保持する.

        Args:
            client (GlideClient): session dataとLua scriptを実行する接続済みclient.
            ttl (int): create/refresh時に設定するTTL秒数. Valkey EXが受け入れる正の値を渡す.
            key_prefix (str): session keyの先頭に付加するnamespace prefix.

        Notes:
            key_prefixを共有するstoreは同じsession namespaceを操作する.
        """
        self._client: GlideClient = client
        self._ttl: int = ttl
        self._prefix: str = key_prefix

    # -- key helpers ----------------------------------------------------------

    def _session_key(self, token: str) -> str:
        """tokenからValkey session keyを構成する.

        Args:
            token (str): sessionを一意に識別するtoken.

        Returns:
            str: key_prefixを含むsession:{token}形式のValkey key.
        """
        return f"{self._prefix}session:{token}"

    def _user_key(self, user_id: int) -> str:
        """user識別子からValkey reverse mapping keyを構成する.

        Args:
            user_id (int): active sessionを検索するuserの識別子.

        Returns:
            str: key_prefixを含むuser_session:{user_id}形式のValkey key.
        """
        return f"{self._prefix}user_session:{user_id}"

    # -- SessionStore Protocol methods ----------------------------------------

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """userのactive sessionを新しいtokenとdataでatomicに置き換える.

        Args:
            user_id (int): sessionを所有するuserの識別子.
            token (str): 新sessionに割り当てる一意なtoken.
            data (SessionData): JSONとして保存するsession authorizationとclient state.

        Returns:
            None: session keyとuser reverse mappingを保存し値を返さずに完了する.

        Notes:
            同一userのold sessionがある場合は先に削除する.
            session keyとreverse mappingは同じTTL秒数で保存する.
        """
        _ = await self._client.invoke_script(
            self._CREATE_SCRIPT,
            keys=[self._user_key(user_id), self._session_key(token)],
            args=[
                f"{self._prefix}session:",
                json.dumps(asdict(data)),
                str(self._ttl),
                token,
            ],
        )

    async def get(self, token: str) -> SessionData | None:
        """tokenに対応するSessionDataを取得する.

        Args:
            token (str): 取得するsessionのtoken.

        Returns:
            SessionData | None: JSONを復元したsession data. keyが存在しない場合はNone.

        Raises:
            json.JSONDecodeError: Valkeyに保存されたsession JSONが破損している場合.
            TypeError: 保存JSONがSessionDataのrequired fieldに適合しない場合.
        """
        raw = await self._client.get(self._session_key(token))
        if raw is None:
            return None
        return SessionData(**json.loads(raw))  # pyright: ignore[reportAny] — json.loads returns Any

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """User reverse mappingからactive SessionDataを取得する.

        Args:
            user_id (int): active sessionを検索するuserの識別子.

        Returns:
            SessionData | None: active session data. reverse mappingがない場合はNone.

        Raises:
            UnicodeDecodeError: reverse mappingのtoken bytesがUTF-8として不正な場合.
            json.JSONDecodeError: 参照先session JSONが破損している場合.
            TypeError: 参照先JSONがSessionDataのrequired fieldに適合しない場合.
        """
        token_raw = await self._client.get(self._user_key(user_id))
        if token_raw is None:
            return None
        token = token_raw.decode()
        return await self.get(token)

    async def delete(self, token: str) -> None:
        """tokenに対応するsessionと一致するreverse mappingをatomicに削除する.

        Args:
            token (str): 削除するsessionのtoken.

        Returns:
            None: 対象keyを削除または存在しないまま完了し値を返さない.

        Notes:
            reverse mappingは同tokenを指す場合だけ削除する.
            concurrent loginが作った新しいsession mappingは削除しない.
        """
        _ = await self._client.invoke_script(
            self._DELETE_SCRIPT,
            keys=[self._session_key(token)],
            args=[
                "user_id",
                f"{self._prefix}user_session:",
                token,
            ],
        )

    async def exists(self, token: str) -> bool:
        """tokenのsession keyがValkeyに存在するか確認する.

        Args:
            token (str): 存在確認するsessionのtoken.

        Returns:
            bool: session keyが存在する場合はTrue. 存在しない場合はFalse.
        """
        result = await self._client.exists([self._session_key(token)])
        return result > 0

    async def refresh(self, token: str) -> bool:
        """sessionとuser reverse mappingのTTLをatomicに更新する.

        Args:
            token (str): TTLを更新するsessionのtoken.

        Returns:
            bool: session keyが存在してTTL更新できた場合はTrue. 存在しない場合はFalse.

        Notes:
            user reverse mappingはsession JSONのuser_idから求める. sessionと同じTTL秒数へ更新する.
        """
        result = await self._client.invoke_script(
            self._REFRESH_SCRIPT,
            keys=[self._session_key(token)],
            args=[
                str(self._ttl),
                "user_id",
                f"{self._prefix}user_session:",
            ],
        )
        return bool(result)

    async def delete_by_user(self, user_id: int) -> None:
        """User reverse mappingからactive sessionをatomicに削除する.

        Args:
            user_id (int): 削除するactive sessionを所有するuserの識別子.

        Returns:
            None: sessionを削除または存在しないまま完了し値を返さない.

        Notes:
            reverse mappingがない場合はno-opでありidempotentに利用できる.
        """
        _ = await self._client.invoke_script(
            self._DELETE_BY_USER_SCRIPT,
            keys=[self._user_key(user_id)],
            args=[f"{self._prefix}session:"],
        )

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """Active sessionのprivilegesとrole_idsをatomicに更新する.

        Args:
            user_id (int): authorizationを更新するactive sessionの所有者.
            authorization (SessionAuthorization): 保存するPrivilege bitsetとrole ID snapshot.

        Returns:
            bool: active reverse mappingとsessionが存在して更新できた場合はTrue. それ以外はFalse.

        Notes:
            他fieldとuser reverse mappingは維持する.
            session TTLを維持する. script実行時にTTLが0以下なら3600秒へfallbackする.
        """
        result = await self._client.invoke_script(
            self._UPDATE_AUTHORIZATION_SCRIPT,
            keys=[self._user_key(user_id)],
            args=[
                f"{self._prefix}session:",
                str(int(authorization.privileges)),
                json.dumps(list(authorization.role_ids)),
            ],
        )
        return bool(result)

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """Active sessionのpm_private flagをatomicに更新する.

        Args:
            user_id (int): private message設定を更新するactive sessionの所有者.
            enabled (bool): private messageを許可するならTrue. 拒否するならFalse.

        Returns:
            bool: active reverse mappingとsessionが存在して更新できた場合はTrue. それ以外はFalse.

        Notes:
            他fieldとuser reverse mappingを維持する.
            TTL付きkeyは残りのmillisecond TTLを維持する. expiry直前は最低1msで再保存する.
            expirationなしのkeyはexpirationを付けずに再保存する.
        """
        result = await self._client.invoke_script(
            self._UPDATE_PM_PRIVATE_SCRIPT,
            keys=[self._user_key(user_id)],
            args=[
                f"{self._prefix}session:",
                "1" if enabled else "0",
            ],
        )
        return bool(result)

    async def list_active_sessions(self) -> list[SessionData]:
        """User reverse mappingをSCANして現在取得できるactive sessionを列挙する.

        Returns:
            list[SessionData]: scan中にreverse mappingから復元できたsession dataのlist.

        Raises:
            ValueError: matching reverse mapping keyのuser ID suffixが整数でない場合.
            UnicodeDecodeError: reverse mappingのtoken bytesがUTF-8として不正な場合.
            json.JSONDecodeError: 参照先session JSONが破損している場合.
            TypeError: 参照先JSONがSessionDataのrequired fieldに適合しない場合.

        Notes:
            Valkey SCANはatomic snapshotでも順序保証でもない.
            concurrent create/deleteやTTL expiryが起きうる.
            scan後に取得できないsessionは結果から除外する.
        """
        prefix = f"{self._prefix}user_session:"
        sessions: list[SessionData] = []
        cursor = "0"
        while True:
            cursor_str, keys = await self._client.scan(cursor, match=prefix + "*", count=100)
            for key in keys:
                raw_str = key.decode() if isinstance(key, bytes) else str(key)
                user_id_str = raw_str.removeprefix(prefix)
                session = await self.get_by_user(int(user_id_str))
                if session is not None:
                    sessions.append(session)
            cursor = cursor_str.decode() if isinstance(cursor_str, bytes) else str(cursor_str)
            if cursor == "0":
                break
        return sessions
