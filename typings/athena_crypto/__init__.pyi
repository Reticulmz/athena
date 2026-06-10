"""Type stubs for athena_crypto module."""

def decrypt_score_payload(
    encrypted: bytes,
    iv: bytes,
    osu_version: str | None,
) -> tuple[str, bool]: ...
