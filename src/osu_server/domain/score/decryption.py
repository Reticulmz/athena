"""Score payload decryption value objects."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecryptedPayload:
    """Decrypted score payload with checksum validation status."""

    plaintext: str
    checksum_valid: bool
