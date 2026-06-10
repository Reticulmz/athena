"""Unit tests for score crypto service."""

import base64

import pytest

from osu_server.services.score_crypto import DecryptedPayload, decrypt_score_payload
from osu_server.shared.errors import DecryptionError


def test_decrypt_real_payload() -> None:
    """Test decryption with real osu! payload."""
    iv_b64 = "l5++m1KWx1SO2vg8d1TDCOgnU01NLUUSC9DOlJ5F/HI="
    encrypted_b64 = (
        "k+JrPEaEO6bYw97BJ5IrYhhjBF61T7RjekI2ZETLKwJPdct8wy2mngloX73XoZOUw+Yxc9j3qDDmHFQIven+i"
        "hXmpX9SKcWQymCt73W3TYnJBHLN1PXlcrB1l3N9K8D+jFp1WmVHO1l1dBYdZqxgx0hNcZ2VadtDCGVlCvzZC"
        "DiZs5KZhBBHTMdEUVrAzs+F01+XDKu7eoC7VSoyIaauJQ=="
    )
    osu_version = "20260412"

    iv = base64.b64decode(iv_b64)
    encrypted = base64.b64decode(encrypted_b64)

    result = decrypt_score_payload(encrypted, iv, osu_version)

    assert isinstance(result, DecryptedPayload)
    assert result.plaintext.startswith("8119fb28af74b9445f4a685f8b09eec2:")
    assert isinstance(result.checksum_valid, bool)


def test_decrypt_with_legacy_key() -> None:
    """Test decryption with None osu_version uses legacy key."""
    iv = b"0" * 32
    encrypted = b"0" * 32

    with pytest.raises(DecryptionError):
        _ = decrypt_score_payload(encrypted, iv, None)


def test_decrypt_invalid_iv_raises_error() -> None:
    """Test invalid IV size raises DecryptionError."""
    encrypted = b"0" * 32
    invalid_iv = b"short"

    with pytest.raises(DecryptionError):
        _ = decrypt_score_payload(encrypted, invalid_iv, "20260412")
