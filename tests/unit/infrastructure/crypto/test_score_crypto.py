"""Unit tests for ScoreCrypto (athena_crypto Rust module)."""

import base64

import athena_crypto
import pytest

from osu_server.infrastructure.crypto.score_crypto import (
    decrypt_score_payload as decrypt_score_payload_wrapper,
)

EXPECTED_PLAINTEXT_LENGTH = 160
RIJNDAEL_BLOCK_SIZE = 32


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
    assert len(plaintext) == EXPECTED_PLAINTEXT_LENGTH
    assert plaintext.startswith("8119fb28af74b9445f4a685f8b09eec2:")


def test_wrapper_strips_pkcs7_padding_from_real_payload() -> None:
    """Python wrapper accepts a real payload with PKCS#7 padding."""
    iv_b64 = "l5++m1KWx1SO2vg8d1TDCOgnU01NLUUSC9DOlJ5F/HI="
    score_b64 = (
        "k+JrPEaEO6bYw97BJ5IrYhhjBF61T7RjekI2ZETLKwJPdct8wy2mngloX73XoZOUw+Yxc9j3qDDmHFQIven+i"
        "hXmpX9SKcWQymCt73W3TYnJBHLN1PXlcrB1l3N9K8D+jFp1WmVHO1l1dBYdZqxgx0hNcZ2VadtDCGVlCvzZC"
        "DiZs5KZhBBHTMdEUVrAzs+F01+XDKu7eoC7VSoyIaauJQ=="
    )

    result = decrypt_score_payload_wrapper(
        base64.b64decode(score_b64),
        base64.b64decode(iv_b64),
        "20260412",
    )

    assert result.checksum_valid is False
    assert result.plaintext.endswith(":50695543")
    assert "\x07" not in result.plaintext


def test_wrapper_honors_crypto_checksum_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python wrapper preserves athena_crypto checksum failures."""

    def decrypt_with_bad_checksum(
        _encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> tuple[str, bool]:
        return "payload" + chr(1), False

    monkeypatch.setattr(athena_crypto, "decrypt_score_payload", decrypt_with_bad_checksum)

    result = decrypt_score_payload_wrapper(b"encrypted", b"0" * RIJNDAEL_BLOCK_SIZE, "20260412")

    assert result.plaintext == "payload"
    assert result.checksum_valid is False


def test_decrypt_with_osuver_key() -> None:
    """Test decryption with osuver-based key."""
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
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
