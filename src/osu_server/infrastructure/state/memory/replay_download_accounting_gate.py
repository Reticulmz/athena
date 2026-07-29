"""Replay download accounting gate の in-memory 実装を提供する module."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

_ClaimKey = TypeVar("_ClaimKey", int, tuple[int, int])


class InMemoryReplayDownloadAccountingGate:
    """Replay download accounting marker を process local memory に保存する gate.

    Attributes:
        _time_func (Callable[[], float]): 現在時刻を秒で返す注入可能な monotonic clock.
        _view_markers (dict[tuple[int, int], float]): viewer と score ごとの marker expiration.
        _activity_markers (dict[int, float]): viewer ごとの activity marker expiration.

    Notes:
        claim 時に期限切れ marker を削除し,Valkey adapter と同じ first-claim semantics を提供する.
        process local memory のため永続性と cross-process atomicity は持たない.
    """

    def __init__(self, *, time_func: Callable[[], float] | None = None) -> None:
        """Clock を指定して replay download accounting gate を初期化する.

        Args:
            time_func (Callable[[], float] | None): 現在時刻を秒で返す clock.未指定時は
                time.monotonic.

        Notes:
            test では time_func を注入して TTL expiration を決定的に検証できる.
        """
        self._time_func: Callable[[], float] = time_func or time.monotonic
        self._view_markers: dict[tuple[int, int], float] = {}
        self._activity_markers: dict[int, float] = {}

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

        Notes:
            duplicate identity は viewer_user_id と score_id だけで構成する.
        """
        return self._claim(
            self._view_markers,
            (viewer_user_id, score_id),
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
            None: marker 削除処理の完了を表す.

        Notes:
            存在しない marker の削除は成功扱いにする.
        """
        _ = self._view_markers.pop((viewer_user_id, score_id), None)

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

        Notes:
            throttle identity は viewer_user_id だけで構成する.
        """
        return self._claim(
            self._activity_markers,
            viewer_user_id,
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
            None: marker 削除処理の完了を表す.

        Notes:
            存在しない marker の削除は成功扱いにする.
        """
        _ = self._activity_markers.pop(viewer_user_id, None)

    def _claim(
        self,
        markers: MutableMapping[_ClaimKey, float],
        key: _ClaimKey,
        ttl_seconds: int,
    ) -> bool:
        """期限切れ marker を除去して key の first-claim を試行する.

        Args:
            markers (MutableMapping[_ClaimKey, float]): expiration timestamp を持つ mutable
                marker storage.
            key (_ClaimKey): claim 対象の marker identity.
            ttl_seconds (int): 新規 marker を保持する正の秒数.

        Returns:
            bool: marker を新規作成した場合は True,既存 marker が有効なら False.

        Raises:
            ValueError: ttl_seconds が 1 未満の場合.
        """
        _validate_ttl_seconds(ttl_seconds)

        now = self._time_func()
        self._prune_expired(markers, now)
        if key in markers:
            return False

        markers[key] = now + ttl_seconds
        return True

    @staticmethod
    def _prune_expired(
        markers: MutableMapping[_ClaimKey, float],
        now: float,
    ) -> None:
        """Storage 内の expiration が現在時刻以前の marker を削除する.

        Args:
            markers (MutableMapping[_ClaimKey, float]): 削除対象の mutable marker storage.
            now (float): expiration と比較する現在時刻の秒値.

        Returns:
            None: 期限切れ marker の削除完了を表す.
        """
        expired_keys = [key for key, expires_at in markers.items() if expires_at <= now]
        for key in expired_keys:
            del markers[key]


def _validate_ttl_seconds(ttl_seconds: int) -> None:
    """Marker の TTL 秒数が正であることを検証する.

    Args:
        ttl_seconds (int): 検証する marker の保持秒数.

    Returns:
        None: ttl_seconds が正であることを表す.

    Raises:
        ValueError: ttl_seconds が 1 未満の場合.
    """
    if ttl_seconds < 1:
        raise ValueError("ttl_seconds must be positive")
