"""Athena CLI root helpとenvironment file commandの可観測契約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from athena_cli.commands import env as env_command
from athena_cli.env.dsn import DatabaseConnectionParts, ValkeyConnectionParts
from athena_cli.main import app
from athena_cli.prompts import OsuApiPromptResult

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def test_root_help_shows_only_in_scope_management_commands() -> None:
    """Root helpが管理対象commandだけをlistingし既存description contractを維持することを検証する.

    Returns:
        None: root commandの可視listingと対象外commandの非表示を検証して完了する.
            呼び出し側へ値を返さない.
    """
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
    """未登録commandがusage表示を伴うfailureになることを検証する.

    Returns:
        None: non-zero exit codeとNo such command表示を検証して完了する. 呼び出し側へ値を返さない.
    """
    result = runner.invoke(app, ["unknown-command"])

    assert result.exit_code != 0
    assert "Usage:" in result.output
    assert "No such command" in result.output


class FakeEnvInitPromptAdapter:
    """environment初期化が必要とする入力を固定値で返すprompt adapter fakeを提供する.

    Attributes:
        sections (tuple[str, ...]): init時に選択済みとして返す設定section.
        production_confirmed (bool): production上書きconfirmationとして返す値.
    """

    def __init__(
        self,
        *,
        sections: tuple[str, ...] = ("database", "valkey", "osu_api"),
        production_confirmed: bool = True,
    ) -> None:
        """section選択とproduction confirmationの既定値を初期化する.

        Args:
            sections (tuple[str, ...]): init時に返す設定section. 既定では全sectionを返す.
            production_confirmed (bool): production上書きを許可するconfirmation値.
        """
        self.sections: tuple[str, ...]
        self.sections = sections
        self.production_confirmed: bool
        self.production_confirmed = production_confirmed

    def select_sections(self) -> tuple[str, ...]:
        """設定収集対象として初期化時に指定したsectionを返す.

        Returns:
            tuple[str, ...]: init commandが収集するsection名.
        """
        return self.sections

    def collect_database_parts(self) -> DatabaseConnectionParts:
        """固定のdatabase接続情報を返す.

        Returns:
            DatabaseConnectionParts: test environment fileに書き込むdatabase接続情報.
        """
        return DatabaseConnectionParts(
            host="localhost",
            port=5432,
            database="athena",
            username="athena",
            password="db-password",
        )

    def collect_valkey_parts(self) -> ValkeyConnectionParts:
        """固定のValkey接続情報を返す.

        Returns:
            ValkeyConnectionParts: test environment fileに書き込むValkey接続情報.
        """
        return ValkeyConnectionParts(
            host="localhost",
            port=6379,
            database=0,
            username=None,
            password=None,
        )

    def collect_osu_api_config(self) -> OsuApiPromptResult:
        """有効化済みのofficial osu! API credentialを返す.

        Returns:
            OsuApiPromptResult: environment fileに書き込む固定API設定.
        """
        return OsuApiPromptResult(
            enabled=True,
            client_id="1234",
            client_secret="osu-secret",
        )

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """表示messageを検証せず初期化時のproduction confirmationを返す.

        Args:
            message (str): commandが表示するconfirmation message.
            default (bool): commandが渡す既定confirmation値.

        Returns:
            bool: construction時に指定したproduction confirmation値.
        """
        _ = message
        _ = default
        return self.production_confirmed


def create_fake_env_init_prompt_adapter() -> FakeEnvInitPromptAdapter:
    """全sectionを選択しproductionも確認済みのprompt adapter fakeを作成する.

    Returns:
        FakeEnvInitPromptAdapter: 通常のinteractive init成功用adapter.
    """
    return FakeEnvInitPromptAdapter()


def create_unconfirmed_production_prompt_adapter() -> FakeEnvInitPromptAdapter:
    """production上書きを確認しないprompt adapter fakeを作成する.

    Returns:
        FakeEnvInitPromptAdapter: production overwrite拒否用adapter.
    """
    return FakeEnvInitPromptAdapter(production_confirmed=False)


def create_forbidden_prompt_adapter() -> FakeEnvInitPromptAdapter:
    """non-interactive pathでpromptが作られた場合に失敗させるfactoryを提供する.

    Returns:
        FakeEnvInitPromptAdapter: このfactoryは正常値を返さずに例外を送出する.

    Raises:
        AssertionError: non-interactive commandがprompt adapterを生成した場合.
    """
    raise AssertionError("prompt adapter must not be created")


def test_interactive_env_init_creates_file_and_reports_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Interactive env initが選択値からfileを作りpathを表示することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): prompt factory、server root、current directoryを
            置き換えるfixture.
        tmp_path (Path): environment file作成を隔離するpytest temporary directory.

    Returns:
        None: CLI出力と作成fileのdatabaseとValkeyとAPI設定を検証して完了する.
            呼び出し側へ値を返さない.
    """
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_fake_env_init_prompt_adapter,
    )

    server_root = tmp_path / "server"
    server_root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(env_command, "server_project_root", lambda: server_root)
    monkeypatch.chdir(cwd)
    result = runner.invoke(app, ["env", "init", "test"])

    assert result.exit_code == 0
    assert "Environment file written: .env.test" in result.output
    env_content = (server_root / ".env.test").read_text(encoding="utf-8")
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
    """Interactive env initが既存fileをforceなしで置換しないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): prompt factoryとserver rootを置き換えるfixture.
        tmp_path (Path): 既存environment fileを配置するpytest temporary directory.

    Returns:
        None: failure messageと既存内容の保持を検証して完了する. 呼び出し側へ値を返さない.
    """
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_fake_env_init_prompt_adapter,
    )

    monkeypatch.setattr(env_command, "server_project_root", lambda: tmp_path)
    _ = (tmp_path / ".env.test").write_text("EXISTING=value\n", encoding="utf-8")
    result = runner.invoke(app, ["env", "init", "test"])

    assert result.exit_code != 0
    assert "Environment file already exists: .env.test" in result.output
    assert (tmp_path / ".env.test").read_text(encoding="utf-8") == "EXISTING=value\n"


def test_interactive_env_init_requires_production_overwrite_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Interactive production env initがunconfirmed overwriteを拒否することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): confirmationなしadapterとserver rootを設定するfixture.
        tmp_path (Path): production environment fileを配置するpytest temporary directory.

    Returns:
        None: overwrite拒否messageと既存内容の保持を検証して完了する. 呼び出し側へ値を返さない.
    """
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_unconfirmed_production_prompt_adapter,
    )

    monkeypatch.setattr(env_command, "server_project_root", lambda: tmp_path)
    _ = (tmp_path / ".env.production").write_text("EXISTING=value\n", encoding="utf-8")
    result = runner.invoke(app, ["env", "init", "production", "--force"])

    assert result.exit_code != 0
    assert "Overwriting .env.production requires --force" in result.output
    assert (tmp_path / ".env.production").read_text(encoding="utf-8") == "EXISTING=value\n"


def test_non_interactive_env_init_creates_file_from_process_env_without_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """non-interactive env initがprocess環境からfileを作りpromptを使わないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): prompt factory、process環境、server rootを
            置き換えるfixture.
        tmp_path (Path): environment file作成を隔離するpytest temporary directory.

    Returns:
        None: CLI出力とprocess由来のfile内容を検証して完了する. 呼び出し側へ値を返さない.
    """
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

    monkeypatch.setattr(env_command, "server_project_root", lambda: tmp_path)
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code == 0
    assert "Environment file written: .env.test" in result.output
    env_content = (tmp_path / ".env.test").read_text(encoding="utf-8")
    assert (
        "DATABASE_URL=postgresql+asyncpg://athena:db-password@localhost:5432/athena" in env_content
    )
    assert "VALKEY_URL=redis://localhost:6379/0" in env_content
    assert "ENVIRONMENT=test" in env_content


def test_non_interactive_env_init_lists_missing_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """non-interactive env initが不足必須値をfile作成前に一覧表示することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): prompt factoryと必須値なしのprocess環境を設定するfixture.
        tmp_path (Path): file非作成を確認するpytest temporary directory.

    Returns:
        None: missing value messageとfile非存在を検証して完了する. 呼び出し側へ値を返さない.
    """
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_forbidden_prompt_adapter,
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VALKEY_URL", raising=False)

    monkeypatch.setattr(env_command, "server_project_root", lambda: tmp_path)
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code != 0
    assert "Missing required environment values: DATABASE_URL, VALKEY_URL" in result.output
    assert not (tmp_path / ".env.test").exists()


def test_non_interactive_env_init_rejects_existing_file_without_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """non-interactive env initが既存fileをforceなしで置換しないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): prompt factory、process環境、server rootを
            置き換えるfixture.
        tmp_path (Path): 既存environment fileを配置するpytest temporary directory.

    Returns:
        None: failure messageと既存内容の保持を検証して完了する. 呼び出し側へ値を返さない.
    """
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

    monkeypatch.setattr(env_command, "server_project_root", lambda: tmp_path)
    _ = (tmp_path / ".env.test").write_text("EXISTING=value\n", encoding="utf-8")
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code != 0
    assert "Environment file already exists: .env.test" in result.output
    assert (tmp_path / ".env.test").read_text(encoding="utf-8") == "EXISTING=value\n"


def test_non_interactive_env_init_rejects_invalid_content_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """non-interactive env initが不正なDSNをfile作成前に拒否することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): prompt factory、不正DSN、server rootを設定するfixture.
        tmp_path (Path): file非作成を確認するpytest temporary directory.

    Returns:
        None: validation failure messageとfile非存在を検証して完了する. 呼び出し側へ値を返さない.
    """
    monkeypatch.setattr(
        env_command,
        "create_prompt_adapter",
        create_forbidden_prompt_adapter,
    )
    monkeypatch.setenv("DATABASE_URL", "not-a-dsn")
    monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379/0")

    monkeypatch.setattr(env_command, "server_project_root", lambda: tmp_path)
    result = runner.invoke(app, ["env", "init", "test", "--non-interactive"])

    assert result.exit_code != 0
    assert "Invalid configuration: database_url" in result.output
    assert not (tmp_path / ".env.test").exists()


def test_env_example_outputs_schema_derived_example(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Env exampleが既存fileでなくAppConfig schema由来の内容を表示することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): commandのcurrent directoryをtemporary directoryへ
            置き換えるfixture.
        tmp_path (Path): 無視される既存.example fileを配置するpytest temporary directory.

    Returns:
        None: schema由来の代表行と既存file内容の非表示を検証して完了する. 呼び出し側へ値を返さない.
    """
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
