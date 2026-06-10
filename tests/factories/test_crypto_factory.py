"""Test crypto factory."""

from tests.factories.crypto_factory import make_encrypted_payload


def test_make_encrypted_payload_returns_valid_structure() -> None:
    """Factory produces valid encrypted payload structure."""
    result = make_encrypted_payload()

    assert "iv" in result
    assert "encrypted" in result
    assert "osu_version" in result
    assert isinstance(result["iv"], bytes)
    assert isinstance(result["encrypted"], bytes)
    assert len(result["iv"]) == 32
