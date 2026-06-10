"""Unit tests for Replay domain model."""

from osu_server.domain.score.replay import Replay


def test_replay_creation_with_all_fields() -> None:
    """Replay dataclassが全フィールドを受け入れる。"""
    replay = Replay(
        id=1,
        score_id=100,
        blob_key="replays/2026/06/11/score-100-replay.osr",
        checksum_sha256="a" * 64,
        byte_size=12345,
    )

    assert replay.id == 1
    assert replay.score_id == 100
    assert replay.blob_key == "replays/2026/06/11/score-100-replay.osr"
    assert replay.checksum_sha256 == "a" * 64
    assert replay.byte_size == 12345


def test_replay_without_id() -> None:
    """ID未割り当て(None)のReplayを作成できる。"""
    replay = Replay(
        id=None,
        score_id=200,
        blob_key="replays/test.osr",
        checksum_sha256="b" * 64,
        byte_size=5000,
    )

    assert replay.id is None
    assert replay.score_id == 200


def test_replay_checksum_validation() -> None:
    """Checksum SHA-256が64文字の16進数であることを確認。"""
    # Valid checksum (64 hex chars)
    replay = Replay(
        id=1,
        score_id=100,
        blob_key="test.osr",
        checksum_sha256="0123456789abcdef" * 4,
        byte_size=1000,
    )

    assert len(replay.checksum_sha256) == 64
    assert all(c in "0123456789abcdef" for c in replay.checksum_sha256)


def test_replay_byte_size_positive() -> None:
    """Replay byte_sizeが正の整数であることを確認。"""
    replay = Replay(
        id=1,
        score_id=100,
        blob_key="test.osr",
        checksum_sha256="f" * 64,
        byte_size=1,
    )

    assert replay.byte_size > 0
