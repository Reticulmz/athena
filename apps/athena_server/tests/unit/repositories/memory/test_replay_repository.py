"""メモリ上のリプレイコマンドrepositoryを検証する."""

from __future__ import annotations

import pytest

from osu_server.domain.scores.replay import Replay
from osu_server.repositories.memory.commands.replays import InMemoryReplayCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


@pytest.fixture
def repository() -> InMemoryReplayCommandRepository:
    """各テストに独立したリプレイrepositoryを生成する.

    Returns:
        InMemoryReplayCommandRepository: 空のメモリ上リプレイrepository.
    """
    return InMemoryReplayCommandRepository(InMemoryCommandRepositoryState())


@pytest.fixture
def sample_replay() -> Replay:
    """リプレイ登録テスト用の有効なリプレイを生成する.

    Returns:
        Replay: 固定されたチェックサムと未採番IDを持つリプレイ.
    """
    return Replay(
        id=None,
        score_id=1,
        blob_id=1,
        checksum_sha256="a" * 64,
        byte_size=12345,
    )


async def test_create_assigns_id(
    repository: InMemoryReplayCommandRepository, sample_replay: Replay
) -> None:
    """新規リプレイ登録が最初の識別子と入力チェックサムを返すことを検証する.

    Args:
        repository (InMemoryReplayCommandRepository): 登録操作を実行するメモリ上repository.
        sample_replay (Replay): 登録する未採番リプレイ.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    created = await repository.create(sample_replay)
    assert created.id is not None
    assert created.id == 1
    assert created.checksum_sha256 == sample_replay.checksum_sha256


async def test_create_increments_id(
    repository: InMemoryReplayCommandRepository, sample_replay: Replay
) -> None:
    """連続するリプレイ登録が単調増加する識別子を割り当てることを検証する.

    Args:
        repository (InMemoryReplayCommandRepository): 連続登録を実行するメモリ上repository.
        sample_replay (Replay): 最初に登録するリプレイ.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    first = await repository.create(sample_replay)
    second = await repository.create(
        Replay(
            id=None,
            score_id=2,
            blob_id=2,
            checksum_sha256="b" * 64,
            byte_size=67890,
        )
    )
    assert first.id == 1
    assert second.id == 2


async def test_create_rejects_duplicate_checksum(
    repository: InMemoryReplayCommandRepository, sample_replay: Replay
) -> None:
    """既存チェックサムの再登録がValueErrorで拒否されることを検証する.

    Args:
        repository (InMemoryReplayCommandRepository): 重複検査を実行するメモリ上repository.
        sample_replay (Replay): 既存レコードとして先に登録するリプレイ.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    _ = await repository.create(sample_replay)
    duplicate = Replay(
        id=None,
        score_id=999,
        blob_id=999,
        checksum_sha256=sample_replay.checksum_sha256,
        byte_size=99999,
    )
    with pytest.raises(ValueError, match="checksum_sha256 already exists"):
        _ = await repository.create(duplicate)


async def test_exists_by_checksum_returns_true_when_exists(
    repository: InMemoryReplayCommandRepository, sample_replay: Replay
) -> None:
    """登録済みチェックサムの存在確認が真を返すことを検証する.

    Args:
        repository (InMemoryReplayCommandRepository): 存在確認を実行するメモリ上repository.
        sample_replay (Replay): 先に登録するリプレイ.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    _ = await repository.create(sample_replay)
    exists = await repository.exists_by_checksum(sample_replay.checksum_sha256)
    assert exists is True


async def test_exists_by_checksum_returns_false_when_not_exists(
    repository: InMemoryReplayCommandRepository,
) -> None:
    """未登録チェックサムの存在確認が偽を返すことを検証する.

    Args:
        repository (InMemoryReplayCommandRepository): 存在確認を実行するメモリ上repository.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    exists = await repository.exists_by_checksum("nonexistent_checksum")
    assert exists is False
