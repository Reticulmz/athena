"""Score cryptography service - Rijndael-256 decryption."""

from dataclasses import dataclass

import athena_crypto

from osu_server.shared.errors import DecryptionError


@dataclass(frozen=True, slots=True)
class DecryptedPayload:
    """Decrypted score payload with checksum validation status."""

    plaintext: str
    checksum_valid: bool


def decrypt_score_payload(
    encrypted: bytes,
    iv: bytes,
    osu_version: str | None,
) -> DecryptedPayload:
    """
    Decrypt score payload using Rijndael-256 CBC.

    Preconditions: encrypted and iv are valid byte arrays
    Postconditions: Returns decrypted plaintext with checksum status
    Errors: DecryptionError if decryption fails
    """
    try:
        plaintext, checksum_valid = athena_crypto.decrypt_score_payload(encrypted, iv, osu_version)
        return DecryptedPayload(plaintext=plaintext, checksum_valid=checksum_valid)
    except ValueError as e:
        raise DecryptionError(f"Decryption failed: {e}") from e
