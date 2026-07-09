"""Valkey-backed replay download accounting gate."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol

from glide import Script

if TYPE_CHECKING:
    from glide_shared.constants import TEncodable


class _ValkeyReplayDownloadAccountingClient(Protocol):
    async def invoke_script(
        self,
        script: Script,
        keys: list[TEncodable] | None = None,
        args: list[TEncodable] | None = None,
    ) -> object: ...


class ValkeyReplayDownloadAccountingGate:
    """Replay download accounting marker を Valkey に保存する。

    Key pattern は adapter が所有する。Lua script の SET NX EX により
    first-claim 判定と TTL 設定を atomic に行う。
    """

    _CLAIM_SCRIPT: ClassVar[Script] = Script("""\
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', tonumber(ARGV[2])) then
    return 1
end
return 0""")

    def __init__(
        self,
        client: _ValkeyReplayDownloadAccountingClient,
        *,
        key_prefix: str = "",
    ) -> None:
        """Valkey client と optional key prefix で初期化する。

        Args:
            client: Valkey GLIDE 互換の invoke_script client。
            key_prefix: test や環境分離に使う key prefix。

        Returns:
            None。

        Raises:
            なし。

        Constraints:
            key は viewer user id と score id から adapter 内で構築する。
        """
        self._client: _ValkeyReplayDownloadAccountingClient = client
        self._prefix: str = key_prefix

    def _view_key(self, viewer_user_id: int, score_id: int) -> str:
        return f"{self._prefix}replay_download_accounting:view:{viewer_user_id}:score:{score_id}"

    def _activity_key(self, viewer_user_id: int) -> str:
        return f"{self._prefix}replay_download_accounting:activity:{viewer_user_id}"

    async def claim_replay_view(
        self,
        viewer_user_id: int,
        score_id: int,
        ttl_seconds: int,
    ) -> bool:
        """viewer と score の replay view marker を first-claim する。

        Args:
            viewer_user_id: 認証済み viewer user id。
            score_id: download 対象 score id。
            ttl_seconds: marker を保持する秒数。

        Returns:
            marker を新規作成した場合は True。既存 marker がある場合は False。

        Raises:
            ValueError: ttl_seconds が 1 未満の場合。
            TypeError: Valkey script result が integer ではない場合。

        Constraints:
            duplicate identity は viewer_user_id と score_id だけで構成する。
        """
        return await self._claim(
            self._view_key(viewer_user_id, score_id),
            ttl_seconds,
        )

    async def claim_latest_activity(
        self,
        viewer_user_id: int,
        ttl_seconds: int,
    ) -> bool:
        """viewer の latest activity marker を first-claim する。

        Args:
            viewer_user_id: 認証済み viewer user id。
            ttl_seconds: marker を保持する秒数。

        Returns:
            marker を新規作成した場合は True。既存 marker がある場合は False。

        Raises:
            ValueError: ttl_seconds が 1 未満の場合。
            TypeError: Valkey script result が integer ではない場合。

        Constraints:
            throttle identity は viewer_user_id だけで構成する。
        """
        return await self._claim(
            self._activity_key(viewer_user_id),
            ttl_seconds,
        )

    async def _claim(self, key: str, ttl_seconds: int) -> bool:
        _validate_ttl_seconds(ttl_seconds)

        args: list[TEncodable] = ["1", str(ttl_seconds)]
        result = await self._client.invoke_script(
            self._CLAIM_SCRIPT,
            keys=[key],
            args=args,
        )
        return _claim_result_to_bool(result)


def _claim_result_to_bool(result: object) -> bool:
    if not isinstance(result, int):
        raise TypeError(f"Unexpected replay accounting claim result: {result!r}")
    return result == 1


def _validate_ttl_seconds(ttl_seconds: int) -> None:
    if ttl_seconds < 1:
        raise ValueError("ttl_seconds must be positive")
