from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from athena_cli.errors import CliUserError

if TYPE_CHECKING:
    from pathlib import Path

    from athena_cli.context import EnvironmentName


@dataclass(frozen=True, slots=True)
class EnvironmentFileWriteResult:
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
    if not exists:
        return
    if not force:
        raise CliUserError(f"Environment file already exists: {path}")
    if environment == "production" and not production_confirmed:
        raise CliUserError(
            "Overwriting .env.production requires --force and explicit confirmation."
        )
