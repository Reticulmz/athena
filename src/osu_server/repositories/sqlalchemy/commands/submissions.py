"""SQLAlchemyでscore submission lifecycleを永続化するrepositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.repositories.sqlalchemy.models.score import ScoreSubmissionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyScoreSubmissionCommandRepository:
    """Unit of Work所有sessionでscore submissionを操作するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): score submission操作に使うsession.

        Returns:
            None: repositoryの初期化完了を示す.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """新しいscore submissionを永続化してdomain modelへ変換する.

        Args:
            submission (ScoreSubmission): fingerprintと受信時点のstateを持つ新規submission.

        Returns:
            ScoreSubmission: flushとrefresh後の永続化済みsubmission.

        Raises:
            ValueError: 同じfingerprintのsubmissionが既に存在する場合.
            SQLAlchemyError: fingerprint重複以外の永続化処理に失敗した場合.

        Notes:
            このmethodはUnit of Workをcommitしない.
        """
        model = ScoreSubmissionModel(
            fingerprint=submission.fingerprint,
            user_id=submission.user_id,
            beatmap_checksum=submission.beatmap_checksum,
            submitted_at=submission.submitted_at,
            state=submission.state.value,
            result_snapshot=submission.result_snapshot,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "fingerprint" in str(exc):
                msg = f"fingerprint already exists: {submission.fingerprint}"
                raise ValueError(msg) from exc
            raise
        await self._session.refresh(model)
        return _submission_to_domain(model)

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """fingerprintで保存済みscore submissionを取得する.

        Args:
            fingerprint (str): 取得対象submissionの冪等性識別子.

        Returns:
            ScoreSubmission | None: 対応するsubmission. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (
            await self._session.execute(
                select(ScoreSubmissionModel).where(ScoreSubmissionModel.fingerprint == fingerprint)
            )
        ).scalar_one_or_none()
        return _submission_to_domain(model) if isinstance(model, ScoreSubmissionModel) else None

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """保存済みscore submissionのstateとresult snapshotを更新する.

        Args:
            submission_id (int): 更新対象submissionの永続化識別子.
            state (ScoreSubmissionState): 保存するlifecycle state.
            result_snapshot (dict[str, object] | None): stateに対応する結果. 未指定時はNone.

        Returns:
            None: stateとsnapshotのflush完了を示す.

        Raises:
            ValueError: 指定idのsubmissionが存在しない場合.
            SQLAlchemyError: selectまたはflushに失敗した場合.

        Notes:
            このmethodはUnit of Workをcommitしない.
        """
        model = await self._session.get(ScoreSubmissionModel, submission_id)
        if model is None:
            msg = f"Submission not found: {submission_id}"
            raise ValueError(msg)
        assert isinstance(model, ScoreSubmissionModel)

        model.state = state.value
        model.result_snapshot = result_snapshot
        await self._session.flush()


def _submission_to_domain(model: ScoreSubmissionModel) -> ScoreSubmission:
    """SQLAlchemy score submission modelをdomain modelへ変換する.

    Args:
        model (ScoreSubmissionModel): 永続化層から読み出したsubmission row.

    Returns:
        ScoreSubmission: stateをdomain enumへ復元したscore submission.

    Raises:
        ValueError: 保存されたstateが既知のScoreSubmissionStateでない場合.
    """
    return ScoreSubmission(
        id=model.id,
        fingerprint=model.fingerprint,
        user_id=model.user_id,
        beatmap_checksum=model.beatmap_checksum,
        submitted_at=model.submitted_at,
        state=ScoreSubmissionState(model.state),
        result_snapshot=model.result_snapshot,
    )
