"""Multipart request test data factory."""


def make_multipart_request(
    *,
    score: str = "",
    iv: str = "",
    osuver: str = "20260412",
    pass_: str = "",
) -> dict[str, str]:
    """Create multipart request data for testing."""
    return {
        "score": score,
        "iv": iv,
        "osuver": osuver,
        "pass": pass_,
    }
