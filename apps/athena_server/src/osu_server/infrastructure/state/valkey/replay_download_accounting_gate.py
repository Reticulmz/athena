"""Replay download accounting gate の Valkey 実装を提供する module."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol

from glide import Script

if TYPE_CHECKING:
    from glide_shared.constants import TEncodable


class _ValkeyReplayDownloadAccountingClient(Protocol):
    """Replay accounting Lua script を実行する private Valkey client contract.

    Notes:
        claim と release は adapter が所有する Script object と key/argument を渡して実行する.
    """

    async def invoke_script(
        self,
        script: Script,
        keys: list[TEncodable] | None = None,
        args: list[TEncodable] | None = None,
    ) -> object:
        """Lua script を key と argument で実行し,raw result を返す.

        Args:
            script (Script): 実行する事前登録済み Lua script.
            keys (list[TEncodable] | None): script の KEYS として渡す値.
            args (list[TEncodable] | None): script の ARGV として渡す値.

        Returns:
            object: Valkey client が返す未変換の script result.
        """
        ...


class ValkeyReplayDownloadAccountingGate:
    """Replay download accounting marker を Valkey key として保存する gate.

    Attributes:
        _CLAIM_SCRIPT (ClassVar[Script]): SET NX EX で marker を first-claim する Lua script.
        _RELEASE_SCRIPT (ClassVar[Script]): marker key を削除する Lua script.
        _client (_ValkeyReplayDownloadAccountingClient): claim と release script を実行する client.
        _prefix (str): 環境または test を分離する key prefix.

    Notes:
        view key は `{prefix}replay_download_accounting:view:{viewer_user_id}:score:{score_id}`,
        activity key は `{prefix}replay_download_accounting:activity:{viewer_user_id}` を使用する.
        SET NX EX の Lua script が first-claim 判定と TTL 設定を atomic に実行する.
    """

    _CLAIM_SCRIPT: ClassVar[Script] = Script("""\
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', tonumber(ARGV[2])) then
    return 1
end
return 0""")
    _RELEASE_SCRIPT: ClassVar[Script] = Script("""\
return redis.call('DEL', KEYS[1])""")

    def __init__(
        self,
        client: _ValkeyReplayDownloadAccountingClient,
        *,
        key_prefix: str = "",
    ) -> None:
        """Valkey client と optional key prefix を持つ gate を初期化する.

        Args:
            client (_ValkeyReplayDownloadAccountingClient): Lua script を実行する Valkey client.
            key_prefix (str): test や環境分離に使う key prefix.

        Notes:
            key identity は viewer user id と score id から adapter 内で構築する.
        """
        self._client: _ValkeyReplayDownloadAccountingClient = client
        self._prefix: str = key_prefix

    def _view_key(self, viewer_user_id: int, score_id: int) -> str:
        """Viewer と score の replay view marker に対応する Valkey key を組み立てる.

        Args:
            viewer_user_id (int): key に埋め込む viewer user id.
            score_id (int): key に埋め込む score id.

        Returns:
            str: `{prefix}replay_download_accounting:view:{viewer_user_id}:score:{score_id}` key.
        """
        return f"{self._prefix}replay_download_accounting:view:{viewer_user_id}:score:{score_id}"

    def _activity_key(self, viewer_user_id: int) -> str:
        """Viewer の latest activity marker に対応する Valkey key を組み立てる.

        Args:
            viewer_user_id (int): key に埋め込む viewer user id.

        Returns:
            str: `{prefix}replay_download_accounting:activity:{viewer_user_id}` key.
        """
        return f"{self._prefix}replay_download_accounting:activity:{viewer_user_id}"

    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        """閲覧者と score の replay view marker を first-claim する.

        Args:
            viewer_user_id (int): 認証済み viewer user id.
            score_id (int): download 対象 score id.
            ttl_seconds (int): marker を保持する秒数.

        Returns:
            bool: marker を新規作成した場合は True,既存 marker がある場合は False.

        Raises:
            ValueError: ttl_seconds が 1 未満の場合.
            TypeError: Valkey script result が integer ではない場合.

        Notes:
            duplicate identity は viewer_user_id と score_id だけで構成する.
        """
        return await self._claim(
            self._view_key(viewer_user_id, score_id),
            ttl_seconds,
        )

    async def release_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
    ) -> None:
        """閲覧者と score の replay view marker を削除する.

        Args:
            viewer_user_id (int): 認証済み viewer user id.
            score_id (int): download 対象 score id.

        Returns:
            None: release script 実行の完了を表す.

        Notes:
            存在しない marker の削除は Valkey DEL により成功扱いにする.
        """
        await self._release(self._view_key(viewer_user_id, score_id))

    async def claim_latest_activity(
        self,
        viewer_user_id: int,
        ttl_seconds: int,
    ) -> bool:
        """閲覧者の latest activity marker を first-claim する.

        Args:
            viewer_user_id (int): 認証済み viewer user id.
            ttl_seconds (int): marker を保持する秒数.

        Returns:
            bool: marker を新規作成した場合は True,既存 marker がある場合は False.

        Raises:
            ValueError: ttl_seconds が 1 未満の場合.
            TypeError: Valkey script result が integer ではない場合.

        Notes:
            throttle identity は viewer_user_id だけで構成する.
        """
        return await self._claim(
            self._activity_key(viewer_user_id),
            ttl_seconds,
        )

    async def release_latest_activity(
        self,
        viewer_user_id: int,
    ) -> None:
        """閲覧者の latest activity marker を削除する.

        Args:
            viewer_user_id (int): 認証済み viewer user id.

        Returns:
            None: release script 実行の完了を表す.

        Notes:
            存在しない marker の削除は Valkey DEL により成功扱いにする.
        """
        await self._release(self._activity_key(viewer_user_id))

    async def _claim(self, key: str, ttl_seconds: int) -> bool:
        """Key の first-claim Lua script を実行し,結果を bool へ変換する.

        Args:
            key (str): first-claim 対象の Valkey marker key.
            ttl_seconds (int): 新規 marker を保持する正の秒数.

        Returns:
            bool: marker を新規作成した場合は True,既存 marker がある場合は False.

        Raises:
            ValueError: ttl_seconds が 1 未満の場合.
            TypeError: script result が integer ではない場合.
        """
        _validate_ttl_seconds(ttl_seconds)

        args: list[TEncodable] = ["1", str(ttl_seconds)]
        result = await self._client.invoke_script(
            self._CLAIM_SCRIPT,
            keys=[key],
            args=args,
        )
        return _claim_result_to_bool(result)

    async def _release(self, key: str) -> None:
        """Key の replay accounting marker を release Lua script で削除する.

        Args:
            key (str): 削除する Valkey marker key.

        Returns:
            None: release script 実行の完了を表す.

        Notes:
            key が未存在でも DEL の結果を無視して成功扱いにする.
        """
        _ = await self._client.invoke_script(
            self._RELEASE_SCRIPT,
            keys=[key],
            args=[],
        )


def _claim_result_to_bool(result: object) -> bool:
    """Valkey claim script の raw result を first-claim bool へ変換する.

    Args:
        result (object): claim Lua script が返した raw result.

    Returns:
        bool: result が integer 1 なら True,それ以外の integer なら False.

    Raises:
        TypeError: result が integer ではない場合.
    """
    if not isinstance(result, int):
        raise TypeError(f"Unexpected replay accounting claim result: {result!r}")
    return result == 1


def _validate_ttl_seconds(ttl_seconds: int) -> None:
    """Replay accounting marker の TTL 秒数が正であることを検証する.

    Args:
        ttl_seconds (int): 検証する marker の保持秒数.

    Returns:
        None: ttl_seconds が正であることを表す.

    Raises:
        ValueError: ttl_seconds が 1 未満の場合.
    """
    if ttl_seconds < 1:
        raise ValueError("ttl_seconds must be positive")
