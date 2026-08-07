"""ScoreCrypto Rust adapterとPython wrapperの復号契約を検証するmodule."""

import base64

import pytest

import athena_crypto
from osu_server.infrastructure.crypto.score_crypto import (
    decrypt_score_payload as decrypt_score_payload_wrapper,
)

EXPECTED_PLAINTEXT_LENGTH = 153
RIJNDAEL_BLOCK_SIZE = 32


def test_decrypt_real_payload() -> None:
    """実client payloadを復号しchecksumと平文形式を検証する.

    Returns:
        None: 復号結果を検証して値を返さず完了する.
    """
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

    plaintext, checksum_valid = athena_crypto.decrypt_score_payload(encrypted, iv, osuver)

    assert isinstance(plaintext, str)
    assert checksum_valid is True
    assert len(plaintext) == EXPECTED_PLAINTEXT_LENGTH
    assert plaintext.startswith("8119fb28af74b9445f4a685f8b09eec2:")
    assert "\x07" not in plaintext


def test_wrapper_preserves_crypto_result_from_real_payload() -> None:
    """実payloadをwrapperへ渡しRust crypto結果を保持することを検証する.

    Returns:
        None: wrapper結果を検証して値を返さず完了する.
    """
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

    assert result.checksum_valid is True
    assert result.plaintext.endswith(":50695543")
    assert "\x07" not in result.plaintext


def test_wrapper_preserves_failed_crypto_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crypto adapterが検証失敗を返すときwrapperが結果を保持することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): Rust adapter呼び出しをfakeへ差し替えるfixture.

    Returns:
        None: validation失敗結果を検証して値を返さず完了する.
    """

    def decrypt_without_padding(
        _encrypted: bytes,
        _iv: bytes,
        _osu_version: str | None,
    ) -> tuple[str, bool]:
        """padding除去済みの失敗結果を返すcrypto adapter fakeを提供する.

        Args:
            _encrypted (bytes): fakeが受け取る暗号化score payload.
            _iv (bytes): fakeが受け取る初期化vector.
            _osu_version (str | None): fakeが受け取るosu client version.

        Returns:
            tuple[str, bool]: 固定payloadとchecksum invalid flagの組.
        """
        return "payload", False

    monkeypatch.setattr(athena_crypto, "decrypt_score_payload", decrypt_without_padding)

    result = decrypt_score_payload_wrapper(b"encrypted", b"0" * RIJNDAEL_BLOCK_SIZE, "20260412")

    assert result.plaintext == "payload"
    assert result.checksum_valid is False


def test_decrypt_with_osuver_key() -> None:
    """Osuver keyで不正blockを復号しValueErrorを送出することを検証する.

    Returns:
        None: 失敗時の例外を検証して値を返さず完了する.
    """
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
    iv = b"0" * RIJNDAEL_BLOCK_SIZE

    with pytest.raises(ValueError, match=r"Decryption failed|Invalid"):
        _ = athena_crypto.decrypt_score_payload(encrypted, iv, "b20240101")


def test_decrypt_with_legacy_key() -> None:
    """Legacy keyで不正blockを復号しValueErrorを送出することを検証する.

    Returns:
        None: 失敗時の例外を検証して値を返さず完了する.
    """
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
    iv = b"0" * RIJNDAEL_BLOCK_SIZE

    with pytest.raises(ValueError, match=r"Decryption failed|Invalid"):
        _ = athena_crypto.decrypt_score_payload(encrypted, iv, None)


def test_decrypt_invalid_iv_size() -> None:
    """不正なIV sizeで復号しValueErrorを送出することを検証する.

    Returns:
        None: IV validation例外を検証して値を返さず完了する.
    """
    encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
    invalid_iv = b"short"

    with pytest.raises(ValueError, match=r"IV"):
        _ = athena_crypto.decrypt_score_payload(encrypted, invalid_iv, "b20240101")
