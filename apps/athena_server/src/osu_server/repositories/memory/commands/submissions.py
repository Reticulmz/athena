"""In-memory command 側 score submission repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryScoreSubmissionCommandRepository:
    """Score submission primary record と fingerprint index を command 用に管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """一意な fingerprint を持つ score submission を作成し ID を割り当てる.

        Args:
            submission (ScoreSubmission): 保存する submission. 入力 ID は保存時に置き換える.

        Returns:
            ScoreSubmission: next_submission_id を割り当てて保存した submission.

        Raises:
            ValueError: submission.fingerprint が fingerprint index にすでに存在する場合.

        Notes:
            成功時は next_submission_id, 主記録, fingerprint index を更新する.
        """
        if submission.fingerprint in self._state.submission_id_by_fingerprint:
            msg = f"fingerprint already exists: {submission.fingerprint}"
            raise ValueError(msg)

        created = replace(submission, id=self._state.next_submission_id)
        assert created.id is not None
        self._state.next_submission_id += 1
        self._state.submissions_by_id[created.id] = created
        self._state.submission_id_by_fingerprint[created.fingerprint] = created.id
        return created

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """Fingerprint から保存済み score submission を返す.

        Args:
            fingerprint (str): 検索する submission fingerprint.

        Returns:
            ScoreSubmission | None: index と主記録が存在する submission. 未登録又は不整合時は None.
        """
        submission_id = self._state.submission_id_by_fingerprint.get(fingerprint)
        if submission_id is None:
            return None
        return self._state.submissions_by_id.get(submission_id)

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """保存済み score submission の state と result snapshot を置き換える.

        Args:
            submission_id (int): 更新する submission の識別子.
            state (ScoreSubmissionState): 保存する lifecycle state.
            result_snapshot (dict[str, object] | None): 保存する処理結果 snapshot. 省略時は None.

        Returns:
            None: submission state と result snapshot を保存したことを示す.

        Raises:
            ValueError: submission_id が主記録に存在しない場合.

        Notes:
            result_snapshot が None の場合も既存値を保持せず None で上書きする.
        """
        existing = self._state.submissions_by_id.get(submission_id)
        if existing is None:
            msg = f"Submission not found: {submission_id}"
            raise ValueError(msg)
        self._state.submissions_by_id[submission_id] = replace(
            existing,
            state=state,
            result_snapshot=result_snapshot,
        )
