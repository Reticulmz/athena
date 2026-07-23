"""test用credential形状値を共有するhelperを提供する."""

from __future__ import annotations

FIXED_TEST_PASSWORD_MD5 = "a" * 32


def fixed_test_password_md5() -> str:
    """test専用の固定password_md5値を返す.

    Returns:
        str: 実在credentialではないdeterministicなMD5 hex形式の文字列.
    """
    return FIXED_TEST_PASSWORD_MD5
