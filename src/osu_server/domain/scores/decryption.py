"""score payload の復号結果を表す値オブジェクトを定義する."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecryptedPayload:
    """復号済み score payload と checksum 検証結果を保持する.

    Attributes:
        plaintext (str): 復号後の payload 文字列. 形式の解釈は呼び出し側が担う.
        checksum_valid (bool): 復号時に検証した checksum が一致した場合は True.

    Notes:
        この値オブジェクト自身は復号処理も checksum の再検証も行わない.
    """

    plaintext: str
    checksum_valid: bool
