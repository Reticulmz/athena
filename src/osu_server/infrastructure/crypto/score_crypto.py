"""Score cryptography infrastructure service."""

import athena_crypto

from osu_server.domain.score.decryption import DecryptedPayload
from osu_server.shared.errors import DecryptionError

_RIJNDAEL_BLOCK_SIZE = 32


class ScoreCryptoService:
    """Infrastructure adapter for score payload cryptography."""

    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload:
        return decrypt_score_payload(encrypted, iv, osu_version)


def _strip_pkcs7_padding(plaintext: str) -> tuple[str, bool]:
    if not plaintext:
        return plaintext, False

    padding_size = ord(plaintext[-1])
    if padding_size < 1 or padding_size > _RIJNDAEL_BLOCK_SIZE:
        return plaintext, False

    padding = chr(padding_size) * padding_size
    if not plaintext.endswith(padding):
        return plaintext, False

    return plaintext[:-padding_size], True


def decrypt_score_payload(
    encrypted: bytes,
    iv: bytes,
    osu_version: str | None,
) -> DecryptedPayload:
    """
    Decrypt score payload using Rijndael-256 CBC.

    Preconditions: encrypted and iv are valid byte arrays
    Postconditions: Returns decrypted plaintext with padding removed
    Errors: DecryptionError if decryption fails
    """
    try:
        plaintext, checksum_valid = athena_crypto.decrypt_score_payload(
            encrypted,
            iv,
            osu_version,
        )
    except ValueError as e:
        raise DecryptionError(f"Decryption failed: {e}") from e

    plaintext, padding_valid = _strip_pkcs7_padding(plaintext)
    return DecryptedPayload(
        plaintext=plaintext,
        checksum_valid=checksum_valid and padding_valid,
    )
