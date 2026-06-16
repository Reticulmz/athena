from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from athena_cli.commands import env as env_command
from athena_cli.env.dsn import DatabaseConnectionParts, ValkeyConnectionParts
from athena_cli.main import app
from athena_cli.prompts import OsuApiPromptResult

if TYPE_CHECKING:
    import pytest

runner = CliRunner()


def test_root_help_shows_only_in_scope_management_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "env" in result.output
    assert "db" in result.output
    assert "config" in result.output
    assert "dev" in result.output
    assert "pp" in result.output
    assert "test" in result.output
    assert "server" not in result.output
    assert "worker" not in result.output
    assert "drop" not in result.output
    assert "reset" not in result.output
    assert "seed" not in result.output


def test_unknown_command_fails_with_usage_error() -> None:
    result = runner.invoke(app, ["unknown-command"])

    assert result.exit_code != 0
    assert "Usage:" in result.output
    assert "No such command" in result.output


class FakeEnvInitPromptAdapter:
    def __init__(
        self,
        *,
        sections: tuple[str, ...] = ("database", "valkey", "osu_api"),
        production_confirmed: bool = True,
    ) -> None:
        self.sections: tuple[str, ...]
        self.sections = sections
        self.production_confirmed: bool
        self.production_confirmed = production_confirmed

    def select_sections(self) -> tuple[str, ...]:
        return self.sections

    def collect_database_parts(self) -> DatabaseConnectionParts:
        return DatabaseConnectionParts(
            host="localhost",
            port=5432,
            database="athena",
            username="athena",
            password="db-password",
        )

    def collect_valkey_parts(self) -> ValkeyConnectionParts:
        return ValkeyConnectionParts(
            host="localhost",
            port=6379,
            database=0,
            username=None,
            password=None,
        )

    def collect_osu_api_config(self) -> OsuApiPromptResult:
        return OsuApiPromptResult(
            enabled=True,
            client_id="1234",
            client_secret="osu-secret",
        )

    def confirm(self, message: str, *, default: bool = False) -> bool:
        _ = message
        _ = default
        return self.production_confirmed


def create_fake_env_init_prompt_adapter() -> FakeEnvInitPromptAdapter:
    return FakeEnvInitPromptAdapter()


def create_unconfirmed_production_prompt_adapter() -> FakeEnvInitPromptAdapter:
    return FakeEnvInitPromptAdapter(production_confirmed=False)


def create_forbidden_prompt_adapter() -> FakeEnvInitPromptAdapter:
    raise AssertionError("prompt adapter must not be created")


def test_interactive_env_init_creates_file_and_reports_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_fake_env_init_prompt_adapter,
    )

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["env", "init", "test"])

    assert result.exit_code == 0
    assert "Environment file written: .env.test" in result.output
    env_content = Path(".env.test").read_text(encoding="utf-8")
    assert (
        "DATABASE_URL=postgresql+asyncpg://athena:db-password@localhost:5432/athena" in env_content
    )
    assert "VALKEY_URL=redis://localhost:6379/0" in env_content
    assert "BEATMAP_OFFICIAL_API_CLIENT_ID=1234" in env_content
    assert "BEATMAP_OFFICIAL_API_CLIENT_SECRET=osu-secret" in env_content


def test_interactive_env_init_rejects_existing_file_without_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_fake_env_init_prompt_adapter,
    )

    monkeypatch.chdir(tmp_path)
    _ = Path(".env.test").write_text("EXISTING=value\n", encoding="utf-8")
    result = runner.invoke(app, ["env", "init", "test"])

    assert result.exit_code != 0
    assert "Environment file already exists: .env.test" in result.output
    assert Path(".env.test").read_text(encoding="utf-8") == "EXISTING=value\n"


def test_interactive_env_init_requires_production_overwrite_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_unconfirmed_production_prompt_adapter,
    )

    monkeypatch.chdir(tmp_path)
    _ = Path(".env.production").write_text("EXISTING=value\n", encoding="utf-8")
    result = runner.invoke(app, ["env", "init", "production", "--force"])

    assert result.exit_code != 0
    assert "Overwriting .env.production requires --force" in result.output
    assert Path(".env.production").read_text(encoding="utf-8") == "EXISTING=value\n"


def test_non_interactive_env_init_creates_file_from_process_env_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_forbidden_prompt_adapter,
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://athena:db-password@localhost:5432/athena",
    )
    monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379/0")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code == 0
    assert "Environment file written: .env.test" in result.output
    env_content = Path(".env.test").read_text(encoding="utf-8")
    assert (
        "DATABASE_URL=postgresql+asyncpg://athena:db-password@localhost:5432/athena" in env_content
    )
    assert "VALKEY_URL=redis://localhost:6379/0" in env_content
    assert "ENVIRONMENT=test" in env_content


def test_non_interactive_env_init_lists_missing_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_forbidden_prompt_adapter,
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VALKEY_URL", raising=False)

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code != 0
    assert "Missing required environment values: DATABASE_URL, VALKEY_URL" in result.output
    assert not Path(".env.test").exists()


def test_non_interactive_env_init_rejects_existing_file_without_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_forbidden_prompt_adapter,
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://athena:db-password@localhost:5432/athena",
    )
    monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379/0")

    monkeypatch.chdir(tmp_path)
    _ = Path(".env.test").write_text("EXISTING=value\n", encoding="utf-8")
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code != 0
    assert "Environment file already exists: .env.test" in result.output
    assert Path(".env.test").read_text(encoding="utf-8") == "EXISTING=value\n"


def test_non_interactive_env_init_rejects_invalid_content_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_forbidden_prompt_adapter,
    )
    monkeypatch.setenv("DATABASE_URL", "not-a-dsn")
    monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379/0")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code != 0
    assert "Invalid configuration: database_url" in result.output
    assert not Path(".env.test").exists()


def test_env_example_outputs_schema_derived_example(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = (tmp_path / ".env.example").write_text(
        "DATABASE_URL=from-file\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["env", "example"])

    assert result.exit_code == 0
    assert "DATABASE_URL=" in result.output
    assert "VALKEY_URL=" in result.output
    assert "SERVER_PORT=8000" in result.output
    assert "DATABASE_URL=from-file" not in result.output
