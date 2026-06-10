"""Unit tests for ScoreCrypto (athena_crypto Rust module)."""

import athena_crypto


def test_decrypt_with_osuver_key() -> None:
    """Test decryption with osuver-based key."""
    # Minimal smoke test: verify function signature and basic operation
    # Real decryption test requires actual encrypted payload from osu! client
    encrypted = b"0" * 32  # Placeholder: needs actual encrypted data
    iv = b"0" * 32

    try:
        result = athena_crypto.decrypt_score_payload(encrypted, iv, "b20240101")
        assert isinstance(result, tuple)
        assert len(result) == 2
        plaintext, checksum_valid = result
        assert isinstance(plaintext, str)
        assert isinstance(checksum_valid, bool)
    except ValueError as e:
        # Expected: placeholder data will fail decryption
        assert "Decryption failed" in str(e) or "Invalid" in str(e)


def test_decrypt_with_legacy_key() -> None:
    """Test decryption with legacy key (no osuver)."""
    encrypted = b"0" * 32
    iv = b"0" * 32

    try:
        result = athena_crypto.decrypt_score_payload(encrypted, iv, None)
        assert isinstance(result, tuple)
        assert len(result) == 2
    except ValueError as e:
        assert "Decryption failed" in str(e) or "Invalid" in str(e)


def test_decrypt_invalid_iv_size() -> None:
    """Test decryption with invalid IV size raises error."""
    encrypted = b"0" * 32
    invalid_iv = b"short"

    try:
        athena_crypto.decrypt_score_payload(encrypted, invalid_iv, "b20240101")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass  # Expected
