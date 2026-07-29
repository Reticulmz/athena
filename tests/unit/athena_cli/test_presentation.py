"""CLI presentation helperが返す表示文字列の契約を検証する."""

from __future__ import annotations

from pathlib import Path

from athena_cli.presentation import (
    format_environment_file_written,
    format_production_banner,
    mask_secret,
)


def test_mask_secret_hides_non_empty_values() -> None:
    """空でないsecret値が固定maskへ置換されることを検証する.

    Returns:
        None: mask済み文字列を検証して完了する. 呼び出し側へ値を返さない.
    """
    assert mask_secret("super-secret") == "********"


def test_mask_secret_preserves_empty_values() -> None:
    """空のsecret値は表示しても空文字のままであることを検証する.

    Returns:
        None: 空文字の保持を検証して完了する. 呼び出し側へ値を返さない.
    """
    assert mask_secret("") == ""


def test_production_banner_mentions_target_environment() -> None:
    """production操作用bannerがtarget environmentを明示することを検証する.

    Returns:
        None: 固定banner文字列を検証して完了する. 呼び出し側へ値を返さない.
    """
    assert format_production_banner() == "Target environment: production"


def test_environment_file_written_reports_target_path() -> None:
    """Environment file書き込みmessageがtarget pathを含むことを検証する.

    Returns:
        None: 完了messageを検証して完了する. 呼び出し側へ値を返さない.
    """
    message = format_environment_file_written(Path(".env.test"))

    assert message == "Environment file written: .env.test"
