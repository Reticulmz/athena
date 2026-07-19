"""CLIへ表示する文字列の整形helperを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


SECRET_MASK = "********"


def mask_secret(value: str) -> str:
    """空文字以外のsecret値を固定maskへ置き換える.

    Args:
        value (str): 表示前にmaskする可能性があるsecret値.

    Returns:
        str: 空文字はそのまま返しそれ以外はSECRET_MASKを返す.
    """
    if not value:
        return ""
    return SECRET_MASK


def format_production_banner() -> str:
    """productionをtargetにした操作のwarning bannerを返す.

    Returns:
        str: production targetを示す固定の表示文字列.
    """
    return "Target environment: production"


def format_environment_file_written(path: Path) -> str:
    """Environment fileの書き込み完了messageを整形する.

    Args:
        path (Path): 書き込み済みenvironment fileのpath.

    Returns:
        str: pathを含む完了message.
    """
    return f"Environment file written: {path}"
