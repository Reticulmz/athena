from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


SECRET_MASK = "********"


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return SECRET_MASK


def format_production_banner() -> str:
    return "Target environment: production"


def format_environment_file_written(path: Path) -> str:
    return f"Environment file written: {path}"
