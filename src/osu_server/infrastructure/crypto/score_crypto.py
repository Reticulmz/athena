"""Score cryptography infrastructure service."""

import athena_crypto

from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.shared.errors import DecryptionError


class ScoreCryptoService:
    """Infrastructure adapter for score payload cryptography."""

    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload:
        return decrypt_score_payload(encrypted, iv, osu_version)


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

    return DecryptedPayload(
        plaintext=plaintext,
        checksum_valid=checksum_valid,
    )
