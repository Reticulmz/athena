"""environment fileを安全なoverwrite policyで書き出す."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from pathlib import Path

    from athena_cli.context import EnvironmentName


@dataclass(frozen=True, slots=True)
class EnvironmentFileWriteResult:
    """environment file書き込みのtargetとoverwrite状態を表す.

    Attributes:
        path (Path): 書き込み先environment fileのpath.
        overwritten (bool): 書き込み前に同じpathが存在した場合はTrue.
    """

    path: Path
    overwritten: bool


def write_environment_file(
    *,
    root: Path,
    environment: EnvironmentName,
    content: str,
    force: bool,
    production_confirmed: bool,
) -> EnvironmentFileWriteResult:
    """Target environment用fileへ内容を書き込みoverwrite状態を返す.

    Args:
        root (Path): `.env.<environment>`を作成するdirectory.
        environment (EnvironmentName): target environment名.
        content (str): UTF-8で書き込むenvironment file内容.
        force (bool): 既存fileのoverwriteを要求する場合はTrue.
        production_confirmed (bool): production overwriteを明示確認した場合はTrue.

    Returns:
        EnvironmentFileWriteResult: 書き込み先pathとoverwrite状態.

    Raises:
        CliUserError: 既存fileのoverwrite policyを満たさない場合.
        OSError: target fileへ内容を書き込めない場合.
    """
    path = root / f".env.{environment}"
    exists = path.exists()
    _validate_overwrite_policy(
        path=path,
        environment=environment,
        exists=exists,
        force=force,
        production_confirmed=production_confirmed,
    )
    _ = path.write_text(content, encoding="utf-8")
    return EnvironmentFileWriteResult(path=path, overwritten=exists)


def _validate_overwrite_policy(
    *,
    path: Path,
    environment: EnvironmentName,
    exists: bool,
    force: bool,
    production_confirmed: bool,
) -> None:
    """既存environment fileを置き換える条件を検証する.

    Args:
        path (Path): 書き込み予定のenvironment file path.
        environment (EnvironmentName): target environment名.
        exists (bool): pathが書き込み前に存在する場合はTrue.
        force (bool): overwriteを要求する場合はTrue.
        production_confirmed (bool): production overwriteを確認済みの場合はTrue.

    Returns:
        None: overwriteを許可または不要と判定し値を返さずに完了する.

    Raises:
        CliUserError: 既存fileにforceがないかproduction確認がない場合.
    """
    if not exists:
        return
    if not force:
        raise CliUserError(f"Environment file already exists: {path}")
    if environment == "production" and not production_confirmed:
        raise CliUserError(
            "Overwriting .env.production requires --force and explicit confirmation."
        )
