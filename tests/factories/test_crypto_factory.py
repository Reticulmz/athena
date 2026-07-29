"""crypto payload test data factoryのcontractを検証する."""

from tests.factories.crypto_factory import make_encrypted_payload


def test_make_encrypted_payload_returns_valid_structure() -> None:
    """default暗号化payloadが復号可能なfield構造を持つことを検証する.

    factoryをdefault引数で実行し, ivと暗号文がbytesで存在することを確認する.
    さらにiv長がAESの32 byteであることを確認する.

    Returns:
        None: factoryのobservable payload構造を検証し, 呼び出し側へ値を返さずに完了する.
    """
    result = make_encrypted_payload()

    assert "iv" in result
    assert "encrypted" in result
    assert "osu_version" in result
    assert isinstance(result["iv"], bytes)
    assert isinstance(result["encrypted"], bytes)
    assert len(result["iv"]) == 32
