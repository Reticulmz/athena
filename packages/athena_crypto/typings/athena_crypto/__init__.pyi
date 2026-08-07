"""athena_crypto moduleのpublic type stubs."""

def decrypt_score_payload(
    encrypted: bytes,
    iv: bytes,
    osu_version: str | None = None,
) -> tuple[str, bool]: ...
