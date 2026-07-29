"""Score submission mutation の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState


class ScoreSubmissionCommandRepository(Protocol):
    """Score submission の mutation と idempotency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """Submission を永続化し repository-assigned identity 付きで返す.

        Args:
            submission (ScoreSubmission): 永続化する未保存 ScoreSubmission.

        Returns:
            ScoreSubmission: Repository-assigned identity を含む永続化後の submission.

        Raises:
            ValueError: fingerprint が既存 ScoreSubmission と重複する場合に送出する.
        """
        ...

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """Idempotency check 用に fingerprint から submission を返す.

        Args:
            fingerprint (str): 検索する submission fingerprint.

        Returns:
            ScoreSubmission | None: 一致する submission.存在しない場合は None.
        """
        ...

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """Processing state と任意の result snapshot を永続化する.

        Args:
            submission_id (int): 更新する ScoreSubmission ID.
            state (ScoreSubmissionState): 記録する processing state.
            result_snapshot (dict[str, object] | None): 記録する処理結果 snapshot.未指定時は
                None.

        Returns:
            None: State と snapshot が Unit of Work に反映されたことを示す.

        Raises:
            ValueError: submission_id に対応する ScoreSubmission が存在しない場合に送出する.
        """
        ...
