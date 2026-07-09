"""Password policy values for identity workflows."""

from __future__ import annotations

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 32
PASSWORD_MIN_UNIQUE_CHARS = 4

PASSWORD_COMPROMISED_MESSAGE = (
    "This password has been compromised in a data breach. Please choose a different password."
)
_MD5_HEX_LENGTH = 32
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def validate_plain_password(password: str) -> tuple[str, ...]:
    """Return password policy violations for a plaintext password."""
    messages: list[str] = []

    if len(password) < PASSWORD_MIN_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        messages.append(
            f"Password must be between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters."
        )

    if len(set(password)) < PASSWORD_MIN_UNIQUE_CHARS:
        messages.append(
            f"Password must contain at least {PASSWORD_MIN_UNIQUE_CHARS} unique characters."
        )

    return tuple(messages)


def normalize_legacy_md5_hex(value: str) -> str:
    """Stable legacy MD5 hex credential を canonical form に正規化する.

    Args:
        value: Stable client から受け取った password-md5 credential 候補.

    Returns:
        str: 32文字の hex 値なら lowercase にした credential. それ以外は入力値.

    Raises:
        なし.

    Notes:
        Stable client 互換のため, MD5 hex の大小文字差を認証差や fingerprint 差にしない.
        MD5 は保存用 hash ではなく legacy wire credential の識別だけに使う.
    """
    if len(value) != _MD5_HEX_LENGTH:
        return value
    if any(character not in _HEX_DIGITS for character in value):
        return value
    return value.lower()
