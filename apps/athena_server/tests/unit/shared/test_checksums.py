"""Checksum共有primitiveのunit test."""

import pytest

from osu_server.shared.checksums import MD5_HEX_LENGTH, is_lowercase_md5_hexdigest


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("0" * MD5_HEX_LENGTH, id="zeroes"),
        pytest.param("0123456789abcdef" * 2, id="mixed-lowercase-hex"),
    ],
)
def test_lowercase_md5_hexdigest_accepts_valid_values(value: str) -> None:
    """有効な小文字16進数MD5 hexdigestを受理することを検証する.

    Args:
        value (str): 有効なMD5 hexdigest.

    Returns:
        None: 有効値が受理されたことを示す.

    Raises:
        AssertionError: 有効値が拒否された場合.
    """
    assert is_lowercase_md5_hexdigest(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("a" * (MD5_HEX_LENGTH - 1), id="short"),
        pytest.param("a" * (MD5_HEX_LENGTH + 1), id="long"),
        pytest.param("A" * MD5_HEX_LENGTH, id="uppercase"),
        pytest.param("g" * MD5_HEX_LENGTH, id="non-hex"),
    ],
)
def test_lowercase_md5_hexdigest_rejects_invalid_values(value: str) -> None:
    """不正なMD5 hexdigest表現を拒否することを検証する.

    Args:
        value (str): 長さまたは文字集合が不正な文字列.

    Returns:
        None: 不正値が拒否されたことを示す.

    Raises:
        AssertionError: 不正値が受理された場合.
    """
    assert not is_lowercase_md5_hexdigest(value)
