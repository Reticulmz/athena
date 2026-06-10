"""Unit tests for ScoreCrypto (athena_crypto Rust module)."""

import base64

import athena_crypto


def test_decrypt_real_payload() -> None:
    """Test decryption with real osu! client payload."""
    # Real payload captured from osu! client
    iv_b64 = "l5++m1KWx1SO2vg8d1TDCOgnU01NLUUSC9DOlJ5F/HI="
    score_b64 = (
        "k+JrPEaEO6bYw97BJ5IrYhhjBF61T7RjekI2ZETLKwJPdct8wy2mngloX73XoZOUw+Yxc9j3qDDmHFQIven+i"
        "hXmpX9SKcWQymCt73W3TYnJBHLN1PXlcrB1l3N9K8D+jFp1WmVHO1l1dBYdZqxgx0hNcZ2VadtDCGVlCvzZC"
        "DiZs5KZhBBHTMdEUVrAzs+F01+XDKu7eoC7VSoyIaauJQ=="
    )
    osuver = "20260412"

    iv = base64.b64decode(iv_b64)
    encrypted = base64.b64decode(score_b64)

    plaintext, _ = athena_crypto.decrypt_score_payload(encrypted, iv, osuver)

    assert isinstance(plaintext, str)
    assert len(plaintext) == 160
    assert plaintext.startswith("8119fb28af74b9445f4a685f8b09eec2:")


def test_decrypt_with_osuver_key() -> None:
    """Test decryption with osuver-based key."""
    encrypted = b"0" * 32
    iv = b"0" * 32

    try:
        result = athena_crypto.decrypt_score_payload(encrypted, iv, "b20240101")
        assert isinstance(result, tuple)
        assert len(result) == 2
    except ValueError as e:
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
        _ = athena_crypto.decrypt_score_payload(encrypted, invalid_iv, "b20240101")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
