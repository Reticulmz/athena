"""Replay download accounting gate の抽象 interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ReplayDownloadAccountingGate(Protocol):
    """Replay download accounting の一時 first-claim marker を扱う。

    実装は replay view duplicate cooldown と latest activity throttle を
    temporary state として扱い、durable source of truth にはしない。
    """

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
            ttl_seconds: marker を保持する秒数。caller が policy TTL を渡す。

        Returns:
            marker を新規作成した場合は True。既存 marker がある場合は False。

        Raises:
            ValueError: ttl_seconds が 1 未満の場合。

        Constraints:
            duplicate identity は viewer_user_id と score_id だけで構成する。
        """
        ...

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
            実装依存の一時 state 削除エラー。

        Constraints:
            durable mutation 失敗後の best-effort 補償で使う。
        """
        ...

    async def claim_latest_activity(
        self,
        viewer_user_id: int,
        ttl_seconds: int,
    ) -> bool:
        """viewer の latest activity marker を first-claim する。

        Args:
            viewer_user_id: 認証済み viewer user id。
            ttl_seconds: marker を保持する秒数。caller が policy TTL を渡す。

        Returns:
            marker を新規作成した場合は True。既存 marker がある場合は False。

        Raises:
            ValueError: ttl_seconds が 1 未満の場合。

        Constraints:
            throttle identity は viewer_user_id だけで構成する。
        """
        ...

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
            実装依存の一時 state 削除エラー。

        Constraints:
            durable mutation 失敗後の best-effort 補償で使う。
        """
        ...
