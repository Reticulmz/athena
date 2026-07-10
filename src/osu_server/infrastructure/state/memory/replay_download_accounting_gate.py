"""In-memory replay download accounting gate."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

_ClaimKey = TypeVar("_ClaimKey", int, tuple[int, int])


class InMemoryReplayDownloadAccountingGate:
    """Replay download accounting marker を memory に保存する。

    Tests and in-memory runtime 向けの実装。claim 時に期限切れ marker を削除し、
    Valkey adapter と同じ first-claim semantics を提供する。
    """

    def __init__(self, *, time_func: Callable[[], float] | None = None) -> None:
        """clock を指定して gate を初期化する。

        Args:
            time_func: 現在時刻を秒で返す callable。未指定時は time.monotonic。

        Returns:
            None。

        Raises:
            なし。

        Constraints:
            process local memory のため永続性はない。
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
        """viewer と score の replay view marker を first-claim する。

        Args:
            viewer_user_id: 認証済み viewer user id。
            score_id: download 対象 score id。
            ttl_seconds: marker を保持する秒数。

        Returns:
            marker を新規作成した場合は True。既存 marker がある場合は False。

        Raises:
            ValueError: ttl_seconds が 1 未満の場合。

        Constraints:
            duplicate identity は viewer_user_id と score_id だけで構成する。
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
        """viewer と score の replay view marker を削除する.

        Args:
            viewer_user_id: 認証済み viewer user id。
            score_id: download 対象 score id。

        Returns:
            None。

        Raises:
            なし。

        Constraints:
            存在しない marker の削除は成功扱いにする。
        """
        _ = self._view_markers.pop((viewer_user_id, score_id), None)

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

        Constraints:
            throttle identity は viewer_user_id だけで構成する。
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
        """viewer の latest activity marker を削除する.

        Args:
            viewer_user_id: 認証済み viewer user id。

        Returns:
            None。

        Raises:
            なし。

        Constraints:
            存在しない marker の削除は成功扱いにする。
        """
        _ = self._activity_markers.pop(viewer_user_id, None)

    def _claim(
        self,
        markers: MutableMapping[_ClaimKey, float],
        key: _ClaimKey,
        ttl_seconds: int,
    ) -> bool:
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
        expired_keys = [key for key, expires_at in markers.items() if expires_at <= now]
        for key in expired_keys:
            del markers[key]


def _validate_ttl_seconds(ttl_seconds: int) -> None:
    if ttl_seconds < 1:
        raise ValueError("ttl_seconds must be positive")
