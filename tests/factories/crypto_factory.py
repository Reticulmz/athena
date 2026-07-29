"""stable score payload暗号化test用のdata factoryを提供する."""

import base64


def make_encrypted_payload(
    *,
    iv_b64: str | None = None,
    encrypted_b64: str | None = None,
    osu_version: str = "20260412",
) -> dict[str, bytes | str]:
    """復号testに渡すbase64暗号化payloadを作る.

    Args:
        iv_b64 (str | None): base64形式のinitialization vector. Noneならdefault値.
        encrypted_b64 (str | None): base64形式の暗号文. Noneならdefault値.
        osu_version (str): 暗号化に使うosu! client version.

    Returns:
        dict[str, bytes | str]: bytesへ復号したivと暗号文, client versionを持つpayload.
    """
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
