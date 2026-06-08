from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from athena_cli.env.writer import write_environment_file
from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from pathlib import Path


def test_write_environment_file_creates_target_path(tmp_path: Path) -> None:
    result = write_environment_file(
        root=tmp_path,
        environment="test",
        content="ENVIRONMENT=test\n",
        force=False,
        production_confirmed=False,
    )

    assert result.path == tmp_path / ".env.test"
    assert result.overwritten is False
    assert result.path.read_text(encoding="utf-8") == "ENVIRONMENT=test\n"


def test_existing_file_is_rejected_without_force(tmp_path: Path) -> None:
    target = tmp_path / ".env.test"
    _ = target.write_text("DATABASE_URL=existing\n", encoding="utf-8")

    with pytest.raises(CliUserError):
        _ = write_environment_file(
            root=tmp_path,
            environment="test",
            content="DATABASE_URL=new\n",
            force=False,
            production_confirmed=False,
        )

    assert target.read_text(encoding="utf-8") == "DATABASE_URL=existing\n"


def test_force_overwrites_non_production_file(tmp_path: Path) -> None:
    target = tmp_path / ".env.development"
    _ = target.write_text("OLD=value\n", encoding="utf-8")

    result = write_environment_file(
        root=tmp_path,
        environment="development",
        content="NEW=value\n",
        force=True,
        production_confirmed=False,
    )

    assert result.path == target
    assert result.overwritten is True
    assert target.read_text(encoding="utf-8") == "NEW=value\n"


def test_production_overwrite_requires_force_and_confirmation(tmp_path: Path) -> None:
    target = tmp_path / ".env.production"
    _ = target.write_text("OLD=value\n", encoding="utf-8")

    with pytest.raises(CliUserError):
        _ = write_environment_file(
            root=tmp_path,
            environment="production",
            content="NEW=value\n",
            force=True,
            production_confirmed=False,
        )

    assert target.read_text(encoding="utf-8") == "OLD=value\n"


def test_production_overwrite_allows_force_with_confirmation(tmp_path: Path) -> None:
    target = tmp_path / ".env.production"
    _ = target.write_text("OLD=value\n", encoding="utf-8")

    result = write_environment_file(
        root=tmp_path,
        environment="production",
        content="NEW=value\n",
        force=True,
        production_confirmed=True,
    )

    assert result.overwritten is True
    assert target.read_text(encoding="utf-8") == "NEW=value\n"
