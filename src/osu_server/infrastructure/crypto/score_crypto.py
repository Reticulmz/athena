"""stable score payloadを復号するinfrastructure adapterを提供するmodule.

Rust実装の``athena_crypto``を, score commandが使うdomain value objectへ変換する.
"""

import athena_crypto

from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.shared.errors import DecryptionError


class ScoreCryptoService:
    """score payload復号のservice interfaceを提供するadapter.

    Attributes:
        なし: instance固有の状態を持たず, module関数へ復号を委譲する.
    """

    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload:
        """暗号化済みscore payloadを復号してdomain結果へ変換する.

        Args:
            encrypted (bytes): Rijndael-256 CBCで暗号化されたscore payload.
            iv (bytes): 復号に使用するinitialization vector.
            osu_version (str | None): legacy client version. 未指定時はNone.

        Returns:
            DecryptedPayload: paddingを除去したpayloadとchecksum検証結果.

        Raises:
            DecryptionError: payload, IV, またはclient versionが復号できない場合.
        """
        return decrypt_score_payload(encrypted, iv, osu_version)


def decrypt_score_payload(
    encrypted: bytes,
    iv: bytes,
    osu_version: str | None,
) -> DecryptedPayload:
    """Rijndael-256 CBCでscore payloadを復号してdomain結果を返す.

    Args:
        encrypted (bytes): Rijndael-256 CBCで暗号化されたscore payload.
        iv (bytes): 復号に使用するinitialization vector.
        osu_version (str | None): legacy client version. 未指定時はNone.

    Returns:
        DecryptedPayload: paddingを除去したpayloadとchecksum検証結果.

    Raises:
        DecryptionError: 暗号化payload, IV, またはclient versionが無効な場合.

    Notes:
        この関数はRust拡張の``ValueError``をdomain境界の``DecryptionError``へ変換する.
    """
    try:
        plaintext, checksum_valid = athena_crypto.decrypt_score_payload(
            encrypted,
            iv,
            osu_version,
        )
    except ValueError as e:
        raise DecryptionError(f"Decryption failed: {e}") from e

    return DecryptedPayload(
        plaintext=plaintext,
        checksum_valid=checksum_valid,
    )
