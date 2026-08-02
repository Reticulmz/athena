"""score に対応する replay binary の domain 値を定義する."""

from dataclasses import dataclass


@dataclass(slots=True)
class Replay:
    """永続化した replay binary の識別情報と整合性情報を表す.

    Attributes:
        id (int | None): 永続化後の replay ID. 未永続化時は None.
        score_id (int): replay が属する score の ID.
        blob_id (int): replay binary を保持する blob の ID.
        checksum_sha256 (str): replay binary の SHA-256 checksum.
        byte_size (int): replay binary の byte 数.

    Notes:
        ID の正性,checksum の形式,byte_size の範囲はこの dataclass では検証しない.
    """

    id: int | None
    score_id: int
    blob_id: int
    checksum_sha256: str
    byte_size: int
