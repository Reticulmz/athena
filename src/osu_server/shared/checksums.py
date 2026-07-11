"""Checksum文字列表現の共有primitiveを定義する."""

MD5_HEX_LENGTH = 32
_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def is_lowercase_md5_hexdigest(value: str) -> bool:
    """値が小文字16進数のMD5 hexdigestか判定する.

    Args:
        value (str): 判定対象の文字列.

    Returns:
        bool: 長さと文字集合がMD5 hexdigest形式に一致する場合はTrue.

    Notes:
        この関数は文字列表現だけを検証し、MD5の暗号学的安全性は保証しない.
    """
    return len(value) == MD5_HEX_LENGTH and all(
        character in _LOWERCASE_HEX_DIGITS for character in value
    )
