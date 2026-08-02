"""Replay download accounting 用の一時 claim contract を定義する module."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ReplayDownloadAccountingGate(Protocol):
    """Replay download accounting の一時 first-claim marker を扱う contract.

    Notes:
        replay view duplicate cooldown と latest activity throttle は temporary state であり,
        durable source of truth として利用しない.
    """

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
            ttl_seconds (int): caller が policy として渡す marker の保持秒数.

        Returns:
            bool: marker を新規作成した場合は True,既存 marker がある場合は False.

        Raises:
            ValueError: ttl_seconds が 1 未満の場合.

        Notes:
            duplicate identity は viewer_user_id と score_id だけで構成する.
        """
        ...

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
            durable mutation の失敗後に best-effort 補償として使う.
        """
        ...

    async def claim_latest_activity(
        self,
        viewer_user_id: int,
        ttl_seconds: int,
    ) -> bool:
        """閲覧者の latest activity marker を first-claim する.

        Args:
            viewer_user_id (int): 認証済み viewer user id.
            ttl_seconds (int): caller が policy として渡す marker の保持秒数.

        Returns:
            bool: marker を新規作成した場合は True,既存 marker がある場合は False.

        Raises:
            ValueError: ttl_seconds が 1 未満の場合.

        Notes:
            throttle identity は viewer_user_id だけで構成する.
        """
        ...

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
            durable mutation の失敗後に best-effort 補償として使う.
        """
        ...
