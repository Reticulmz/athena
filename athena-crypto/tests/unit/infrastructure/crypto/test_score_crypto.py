"""Unit tests for ScoreCrypto (athena_crypto Rust module)."""

import athena_crypto
import pytest

RIJNDAEL_BLOCK_SIZE = 32


def test_decrypt_with_osuver_key() -> None:
    """Test decryption with osuver-based key."""
    # Minimal smoke test: verify function signature and basic operation
    # Real decryption test requires actual encrypted payload from osu! client
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE  # Placeholder: needs actual encrypted data
    iv = b"0" * RIJNDAEL_BLOCK_SIZE

    with pytest.raises(ValueError, match=r"Decryption failed|Invalid"):
        _ = athena_crypto.decrypt_score_payload(encrypted, iv, "b20240101")


def test_decrypt_with_legacy_key() -> None:
    """Test decryption with legacy key (no osuver)."""
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
    iv = b"0" * RIJNDAEL_BLOCK_SIZE

    with pytest.raises(ValueError, match=r"Decryption failed|Invalid"):
        _ = athena_crypto.decrypt_score_payload(encrypted, iv, None)


def test_decrypt_invalid_iv_size() -> None:
    """Test decryption with invalid IV size raises error."""
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
    invalid_iv = b"short"

    with pytest.raises(ValueError, match=r"IV"):
        _ = athena_crypto.decrypt_score_payload(encrypted, invalid_iv, "b20240101")
