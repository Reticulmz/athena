"""Crypto test data factory."""

import base64


def make_encrypted_payload(
    *,
    iv_b64: str | None = None,
    encrypted_b64: str | None = None,
    osu_version: str = "20260412",
) -> dict[str, bytes | str]:
    """Create encrypted payload for testing."""
    if iv_b64 is None:
        iv_b64 = "l5++m1KWx1SO2vg8d1TDCOgnU01NLUUSC9DOlJ5F/HI="
    if encrypted_b64 is None:
        encrypted_b64 = (
            "k+JrPEaEO6bYw97BJ5IrYhhjBF61T7RjekI2ZETLKwJPdct8wy2mngloX73XoZOUw+Yxc9j3qDDmHFQIven+i"
            "hXmpX9SKcWQymCt73W3TYnJBHLN1PXlcrB1l3N9K8D+jFp1WmVHO1l1dBYdZqxgx0hNcZ2VadtDCGVlCvzZC"
            "DiZs5KZhBBHTMdEUVrAzs+F01+XDKu7eoC7VSoyIaauJQ=="
        )

    return {
        "iv": base64.b64decode(iv_b64),
        "encrypted": base64.b64decode(encrypted_b64),
        "osu_version": osu_version,
    }
