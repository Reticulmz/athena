"""Password policy values for identity workflows."""

from __future__ import annotations

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 32
PASSWORD_MIN_UNIQUE_CHARS = 4

PASSWORD_COMPROMISED_MESSAGE = (
    "This password has been compromised in a data breach. Please choose a different password."
)


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
