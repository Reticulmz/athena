"""Valkey client DSN pathからdatabase IDを解析する契約を検証するmodule."""

import pytest

from osu_server.infrastructure.cache.valkey_client import parse_valkey_database_id


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", None),
        ("/", None),
        ("/0", 0),
        ("/1", 1),
        ("/15", 15),
    ],
)
def test_parse_database_id(path: str, expected: int | None) -> None:
    """有効なDSN pathを解析しexpected database IDを返すことを検証する.

    Args:
        path (str): parametrized Valkey DSN path.
        expected (int | None): pathから得るdatabase IDまたはNone.

    Returns:
        None: parsed database IDを検証して値を返さず完了する.
    """
    assert parse_valkey_database_id(path) == expected


@pytest.mark.parametrize("path", ["/abc", "/1/extra", "/-1"])
def test_parse_database_id_rejects_invalid_path(path: str) -> None:
    """不正なDSN pathを解析しValueErrorを送出することを検証する.

    Args:
        path (str): parametrized invalid Valkey DSN path.

    Returns:
        None: path validation例外を検証して値を返さず完了する.
    """
    with pytest.raises(ValueError, match="Invalid Valkey database path"):
        _ = parse_valkey_database_id(path)
