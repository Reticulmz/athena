"""メモリ上のスコア送信コマンドrepositoryを検証する."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.commands.submissions import (
    InMemoryScoreSubmissionCommandRepository,
)


@pytest.fixture
def repository() -> InMemoryScoreSubmissionCommandRepository:
    """各テストに独立した送信repositoryを生成する.

    Returns:
        InMemoryScoreSubmissionCommandRepository: 空のメモリ上スコア送信repository.
    """
    return InMemoryScoreSubmissionCommandRepository(InMemoryCommandRepositoryState())


@pytest.fixture
def sample_submission() -> ScoreSubmission:
    """送信登録テスト用の有効な未採番送信を生成する.

    Returns:
        ScoreSubmission: 固定fingerprintを持つ受信済み送信.
    """
    return ScoreSubmission(
        id=None,
        fingerprint="abc123",
        user_id=1,
        beatmap_checksum="beatmap_md5",
        submitted_at=datetime.now(tz=UTC),
        state=ScoreSubmissionState.RECEIVED,
        result_snapshot=None,
    )


async def test_create_assigns_id(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """新規送信登録が最初の識別子と入力fingerprintを返すことを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            登録操作を実行するメモリ上repository.
        sample_submission (ScoreSubmission): 登録する未採番送信.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    created = await repository.create(sample_submission)
    assert created.id is not None
    assert created.id == 1
    assert created.fingerprint == sample_submission.fingerprint


async def test_create_increments_id(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """連続する送信登録が単調増加する識別子を割り当てることを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            連続登録を実行するメモリ上repository.
        sample_submission (ScoreSubmission): 最初に登録する送信.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    first = await repository.create(sample_submission)
    second = await repository.create(
        ScoreSubmission(
            id=None,
            fingerprint="def456",
            user_id=2,
            beatmap_checksum="beatmap_md5_2",
            submitted_at=datetime.now(tz=UTC),
            state=ScoreSubmissionState.RECEIVED,
            result_snapshot=None,
        )
    )
    assert first.id == 1
    assert second.id == 2


async def test_create_rejects_duplicate_fingerprint(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """既存fingerprintの再登録がValueErrorで拒否されることを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            重複検査を実行するメモリ上repository.
        sample_submission (ScoreSubmission): 既存レコードとして先に登録する送信.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    _ = await repository.create(sample_submission)
    duplicate = ScoreSubmission(
        id=None,
        fingerprint=sample_submission.fingerprint,
        user_id=999,
        beatmap_checksum="different_checksum",
        submitted_at=datetime.now(tz=UTC),
        state=ScoreSubmissionState.RECEIVED,
        result_snapshot=None,
    )
    with pytest.raises(ValueError, match="fingerprint already exists"):
        _ = await repository.create(duplicate)


async def test_get_by_fingerprint_returns_submission(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """登録済みfingerprintの検索が対応する送信を返すことを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            検索操作を実行するメモリ上repository.
        sample_submission (ScoreSubmission): 先に登録する送信.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    created = await repository.create(sample_submission)
    retrieved = await repository.get_by_fingerprint(sample_submission.fingerprint)
    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.fingerprint == created.fingerprint


async def test_get_by_fingerprint_returns_none_when_not_found(
    repository: InMemoryScoreSubmissionCommandRepository,
) -> None:
    """未登録fingerprintの検索がNoneを返すことを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            検索操作を実行するメモリ上repository.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    retrieved = await repository.get_by_fingerprint("nonexistent")
    assert retrieved is None


async def test_update_state_changes_state(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """登録済み送信の状態更新が後続検索へ反映されることを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            状態更新を実行するメモリ上repository.
        sample_submission (ScoreSubmission): 更新前に登録する送信.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    created = await repository.create(sample_submission)
    assert created.state is ScoreSubmissionState.RECEIVED
    assert created.id is not None

    await repository.update_state(created.id, ScoreSubmissionState.PROCESSING)
    retrieved = await repository.get_by_fingerprint(sample_submission.fingerprint)
    assert retrieved is not None
    assert retrieved.state is ScoreSubmissionState.PROCESSING


async def test_update_state_raises_when_id_not_found(
    repository: InMemoryScoreSubmissionCommandRepository,
) -> None:
    """未登録識別子の状態更新がValueErrorを送出することを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            状態更新を実行するメモリ上repository.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    with pytest.raises(ValueError, match="Submission not found"):
        await repository.update_state(999, ScoreSubmissionState.PROCESSING)


async def test_idempotent_retrieval(
    repository: InMemoryScoreSubmissionCommandRepository,
    sample_submission: ScoreSubmission,
) -> None:
    """同じfingerprintの繰り返し検索が同じ送信を返すことを検証する.

    Args:
        repository (InMemoryScoreSubmissionCommandRepository):
            繰り返し検索を実行するメモリ上repository.
        sample_submission (ScoreSubmission): 先に登録する送信.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    first = await repository.create(sample_submission)
    _ = await repository.get_by_fingerprint(sample_submission.fingerprint)
    retrieved_2 = await repository.get_by_fingerprint(sample_submission.fingerprint)

    assert retrieved_2 is not None
    assert retrieved_2.id == first.id
    assert retrieved_2.fingerprint == first.fingerprint
