"""Server testがowner workspaceのfilesystem pathを解決するhelperを提供する."""

from pathlib import Path

SERVER_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = SERVER_WORKSPACE_ROOT / "alembic.ini"
ALEMBIC_VERSIONS_ROOT = SERVER_WORKSPACE_ROOT / "alembic" / "versions"
