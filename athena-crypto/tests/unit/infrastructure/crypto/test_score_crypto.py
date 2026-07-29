"""athena_crypto の score payload 復号契約を検証する."""

import base64

import athena_crypto
import pytest

RIJNDAEL_BLOCK_SIZE = 32
EXPECTED_PLAINTEXT_LENGTH = 153


def test_decrypt_real_payload_strips_pkcs7_padding() -> None:
    """実際の stable score payload から PKCS#7 padding が除去されることを検証する.

    Returns:
        None: 復号済み plaintext, checksum, 長さ, 境界文字列が既知の契約と一致することを検証する.
    """
    iv_b64 = "l5++m1KWx1SO2vg8d1TDCOgnU01NLUUSC9DOlJ5F/HI="
    score_b64 = (
        "k+JrPEaEO6bYw97BJ5IrYhhjBF61T7RjekI2ZETLKwJPdct8wy2mngloX73XoZOUw+Yxc9j3qDDmHFQIven+i"
        "hXmpX9SKcWQymCt73W3TYnJBHLN1PXlcrB1l3N9K8D+jFp1WmVHO1l1dBYdZqxgx0hNcZ2VadtDCGVlCvzZC"
        "DiZs5KZhBBHTMdEUVrAzs+F01+XDKu7eoC7VSoyIaauJQ=="
    )

    plaintext, checksum_valid = athena_crypto.decrypt_score_payload(
        base64.b64decode(score_b64),
        base64.b64decode(iv_b64),
        "20260412",
    )

    assert checksum_valid is True
    assert len(plaintext) == EXPECTED_PLAINTEXT_LENGTH
    assert plaintext.startswith("8119fb28af74b9445f4a685f8b09eec2:")
    assert plaintext.endswith(":50695543")
    assert "\x07" not in plaintext


def test_decrypt_with_osuver_key() -> None:
    """指定済みの `osuver` を使う key で不正な暗号文の復号失敗を検証する.

    Returns:
        None: 32 byte の placeholder payload が復号失敗として扱われることを検証する.

    Notes:
        実クライアント由来の暗号文はこの smoke test では使用しない.
    """
    # Minimal smoke test: verify function signature and basic operation
    # Real decryption test requires actual encrypted payload from osu! client
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE  # Placeholder: needs actual encrypted data
    iv = b"0" * RIJNDAEL_BLOCK_SIZE

    with pytest.raises(ValueError, match=r"Decryption failed|Invalid"):
        _ = athena_crypto.decrypt_score_payload(encrypted, iv, "b20240101")


def test_decrypt_with_legacy_key() -> None:
    """`osuver` に `None` を指定した legacy key で復号失敗を検証する.

    Returns:
        None: 32 byte の placeholder payload が legacy key でも復号失敗として扱われることを
            検証する.
    """
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
    iv = b"0" * RIJNDAEL_BLOCK_SIZE

    with pytest.raises(ValueError, match=r"Decryption failed|Invalid"):
        _ = athena_crypto.decrypt_score_payload(encrypted, iv, None)


def test_decrypt_invalid_iv_size() -> None:
    """32 byte 以外の IV を指定すると ValueError になることを検証する.

    Returns:
        None: 不正な IV size が ValueError として拒否されることを検証する.
    """
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
    invalid_iv = b"short"

    with pytest.raises(ValueError, match=r"IV"):
        _ = athena_crypto.decrypt_score_payload(encrypted, invalid_iv, "b20240101")
