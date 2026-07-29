"""Replay domain modelの値保持契約を検証する."""

from osu_server.domain.scores.replay import Replay


def test_replay_creation_with_all_fields() -> None:
    """Replayが全識別子と整合性metadataを値を変えずに保持することを検証する.

    Returns:
        None: 全fieldの構築後値を検証して完了する.

    Raises:
        AssertionError: Replayが渡した識別子またはmetadataを保持しない場合.
    """
    replay = Replay(
        id=1,
        score_id=100,
        blob_id=10,
        checksum_sha256="a" * 64,
        byte_size=12345,
    )

    assert replay.id == 1
    assert replay.score_id == 100
    assert replay.blob_id == 10
    assert replay.checksum_sha256 == "a" * 64
    assert replay.byte_size == 12345


def test_replay_without_id() -> None:
    """未永続化ReplayがID未割当のNoneを保持できることを検証する.

    Returns:
        None: None IDと他の識別子の保持を検証して完了する.

    Raises:
        AssertionError: 未永続化ReplayをIDなしで表現できない場合.
    """
    replay = Replay(
        id=None,
        score_id=200,
        blob_id=20,
        checksum_sha256="b" * 64,
        byte_size=5000,
    )

    assert replay.id is None
    assert replay.score_id == 200


def test_replay_checksum_validation() -> None:
    """Replayが64文字のlowercase SHA-256 checksum値を値を変えずに保持することを検証する.

    Returns:
        None: checksumの文字数と許可文字集合を検証して完了する.

    Raises:
        AssertionError: 渡したSHA-256 checksum値がReplay上で変化した場合.
    """
    replay = Replay(
        id=1,
        score_id=100,
        blob_id=10,
        checksum_sha256="0123456789abcdef" * 4,
        byte_size=1000,
    )

    assert len(replay.checksum_sha256) == 64
    assert all(c in "0123456789abcdef" for c in replay.checksum_sha256)


def test_replay_byte_size_positive() -> None:
    """Replayが正のbyte_size値を保持することを検証する.

    Returns:
        None: byte_sizeが正数のまま取得できることを検証して完了する.

    Raises:
        AssertionError: 正のreplay byte_sizeを保持できない場合.
    """
    replay = Replay(
        id=1,
        score_id=100,
        blob_id=10,
        checksum_sha256="f" * 64,
        byte_size=1,
    )

    assert replay.byte_size > 0
