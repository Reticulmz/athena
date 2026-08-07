"""athena_crypto native extensionのtype informationを提供する."""

def decrypt_score_payload(
    encrypted: bytes,
    iv: bytes,
    osu_version: str | None = None,
) -> tuple[str, bool]: ...
