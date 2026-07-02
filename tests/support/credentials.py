"""テスト用 credential 形状値を共有する helper."""

from __future__ import annotations

FIXED_TEST_PASSWORD_MD5 = "a" * 32


def fixed_test_password_md5() -> str:
    """テスト専用の固定 password_md5 値を返す.

    Returns:
        実在 credential ではない deterministic な MD5 hex 形式の文字列.
    """
    return FIXED_TEST_PASSWORD_MD5
