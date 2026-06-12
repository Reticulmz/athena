"""Unit tests for Valkey client DSN parsing."""

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
    assert parse_valkey_database_id(path) == expected


@pytest.mark.parametrize("path", ["/abc", "/1/extra", "/-1"])
def test_parse_database_id_rejects_invalid_path(path: str) -> None:
    with pytest.raises(ValueError, match="Invalid Valkey database path"):
        _ = parse_valkey_database_id(path)
