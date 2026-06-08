from __future__ import annotations

from pathlib import Path

from athena_cli.presentation import (
    format_environment_file_written,
    format_production_banner,
    mask_secret,
)


def test_mask_secret_hides_non_empty_values() -> None:
    assert mask_secret("super-secret") == "********"


def test_mask_secret_preserves_empty_values() -> None:
    assert mask_secret("") == ""


def test_production_banner_mentions_target_environment() -> None:
    assert format_production_banner() == "Target environment: production"


def test_environment_file_written_reports_target_path() -> None:
    message = format_environment_file_written(Path(".env.test"))

    assert message == "Environment file written: .env.test"
