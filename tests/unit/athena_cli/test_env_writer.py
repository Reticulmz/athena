"""environment fileの作成とoverwrite safety policyを検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from athena_cli.env.writer import write_environment_file
from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from pathlib import Path


def test_write_environment_file_creates_target_path(tmp_path: Path) -> None:
    """存在しないtargetにenvironment fileを作成しoverwriteなしと報告することを検証する.

    Args:
        tmp_path (Path): file書き込みを隔離するpytest temporary directory.

    Returns:
        None: 作成pathと内容とoverwrite状態を検証して完了する. 呼び出し側へ値を返さない.
    """
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
    """既存fileをforceなしで置換できず内容が保持されることを検証する.

    Args:
        tmp_path (Path): 既存fileを配置するpytest temporary directory.

    Returns:
        None: CliUserErrorと既存内容の保持を検証して完了する. 呼び出し側へ値を返さない.
    """
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
    """production以外の既存fileはforce指定で置換できることを検証する.

    Args:
        tmp_path (Path): 置換対象fileを配置するpytest temporary directory.

    Returns:
        None: 上書き結果と内容を検証して完了する. 呼び出し側へ値を返さない.
    """
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
    """Production fileの上書きにはforceと明示confirmationが必要なことを検証する.

    Args:
        tmp_path (Path): production target fileを配置するpytest temporary directory.

    Returns:
        None: CliUserErrorと既存内容の保持を検証して完了する. 呼び出し側へ値を返さない.
    """
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
    """Production fileはforceとconfirmationがそろえば置換できることを検証する.

    Args:
        tmp_path (Path): production target fileを配置するpytest temporary directory.

    Returns:
        None: overwrite状態と新しい内容を検証して完了する. 呼び出し側へ値を返さない.
    """
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
