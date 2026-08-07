"""インストール済みathena_crypto wheelのscore payload復号契約を検証するmodule."""

from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path

import athena_crypto

RIJNDAEL_BLOCK_SIZE = 32
EXPECTED_PLAINTEXT_LENGTH = 153


def _consumer_venv_path() -> Path:
    """Wheel-only consumer venvのroot pathをenvironmentから取得する.

    Returns:
        Path: native moduleがloadされる必要があるconsumer virtual environment root.

    Raises:
        AssertionError: verifierがconsumer venv locationをtestへ渡さなかった場合.
    """
    consumer_venv = os.environ.get("ATHENA_CRYPTO_CONSUMER_VENV")
    assert consumer_venv is not None, "ATHENA_CRYPTO_CONSUMER_VENV must identify the consumer venv"
    return Path(consumer_venv).resolve()


def _assert_module_is_loaded_from_consumer_venv() -> None:
    """athena_cryptoがsource treeでなくwheel-only consumer venvからloadされることを検証する.

    Returns:
        None: native moduleのload locationを検証して完了する.
    """
    module_file = athena_crypto.__file__
    assert module_file is not None, "athena_crypto must expose an installed module path"
    module_path = Path(module_file).resolve()
    consumer_venv = _consumer_venv_path()
    assert module_path.is_relative_to(consumer_venv), (
        f"athena_crypto was not loaded from the consumer venv: {module_path}"
    )


def _assert_decryption_raises_value_error(
    encrypted: bytes,
    iv: bytes,
    osu_version: str | None,
    expected_error_fragments: tuple[str, ...],
) -> None:
    """指定inputの復号失敗が公開ValueError contractに一致することを検証する.

    Args:
        encrypted (bytes): native extensionへ渡す暗号化payload.
        iv (bytes): native extensionへ渡すinitialization vector.
        osu_version (str | None): key導出に使うosu! version. Legacy keyではNone.
        expected_error_fragments (tuple[str, ...]): error messageに含まれるべき候補fragment.

    Returns:
        None: ValueErrorとerror messageを検証して完了する.

    Raises:
        AssertionError: ValueErrorが送出されないか、messageが候補fragmentを含まない場合.
    """
    try:
        _ = athena_crypto.decrypt_score_payload(encrypted, iv, osu_version)
    except ValueError as error:
        error_message = str(error)
        assert any(fragment in error_message for fragment in expected_error_fragments), (
            error_message
        )
    else:
        raise AssertionError("decrypt_score_payload must reject the invalid input")


class ScoreCryptoArtifactTests(unittest.TestCase):
    """Wheel-only consumerで公開されるnative復号契約を検証する.

    各testはsource treeではなくconsumer venvからnative moduleをloadすることを前提にする.
    """

    def test_decrypt_real_payload_strips_pkcs7_padding(self) -> None:
        """実際のstable score payloadがwheelから正しく復号されることを検証する.

        Returns:
            None: plaintext、checksum、長さ、境界文字列が既知のcompatibility contractと一致する
                ことを検証して完了する.

        Notes:
            互換性根拠はhttps://github.com/osuAkatsuki/bancho.py/blob/master/app/encryption.py
            の`RijndaelCbc`生成である。score submitは
            `osu!-scoreburgr---------{osu_version}` key、32 byte IV、32 byte block、
            `Pkcs7Padding(32)`を使用することを確認済みである.
        """
        _assert_module_is_loaded_from_consumer_venv()
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

        assert checksum_valid
        assert len(plaintext) == EXPECTED_PLAINTEXT_LENGTH
        assert plaintext.startswith("8119fb28af74b9445f4a685f8b09eec2:")
        assert plaintext.endswith(":50695543")
        assert "\x07" not in plaintext

    def test_decrypt_with_osuver_key_rejects_invalid_ciphertext(self) -> None:
        """Osuver keyで不正なciphertextを復号するとValueErrorになることを検証する.

        Returns:
            None: native extensionが復号失敗をValueErrorとして公開することを検証して完了する.
        """
        _assert_module_is_loaded_from_consumer_venv()
        encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
        iv = b"0" * RIJNDAEL_BLOCK_SIZE

        _assert_decryption_raises_value_error(
            encrypted,
            iv,
            "b20240101",
            ("Decryption failed", "Invalid"),
        )

    def test_decrypt_with_legacy_key_rejects_invalid_ciphertext(self) -> None:
        """Legacy keyで不正なciphertextを復号するとValueErrorになることを検証する.

        Returns:
            None: legacy key pathでもnative extensionの復号失敗が維持されることを検証して完了する.
        """
        _assert_module_is_loaded_from_consumer_venv()
        encrypted = b"0" * RIJNDAEL_BLOCK_SIZE
        iv = b"0" * RIJNDAEL_BLOCK_SIZE

        _assert_decryption_raises_value_error(
            encrypted,
            iv,
            None,
            ("Decryption failed", "Invalid"),
        )

    def test_decrypt_rejects_invalid_iv_size(self) -> None:
        """32 byte以外のIVがValueErrorとして拒否されることを検証する.

        Returns:
            None: native extensionがIV size validationを維持することを検証して完了する.
        """
        _assert_module_is_loaded_from_consumer_venv()
        encrypted = b"0" * RIJNDAEL_BLOCK_SIZE

        _assert_decryption_raises_value_error(
            encrypted,
            b"short",
            "b20240101",
            ("IV",),
        )


if __name__ == "__main__":
    _ = unittest.main()
