"""Bounded-context ownership tests for moved domain language."""

from __future__ import annotations

import ast
from pathlib import Path

from osu_server.domain.beatmaps import Beatmap, BeatmapResolveResult
from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.events.users import UserDisconnected
from osu_server.domain.storage.blobs import Blob, BlobStored

PROJECT_ROOT = Path(__file__).parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"
DOMAIN_ROOT = SOURCE_ROOT / "domain"

OLD_DOMAIN_CONCEPT_PATHS = (
    DOMAIN_ROOT / "beatmap" / "__init__.py",
    DOMAIN_ROOT / "beatmap" / "eligibility.py",
    DOMAIN_ROOT / "beatmap" / "errors.py",
    DOMAIN_ROOT / "beatmap" / "models.py",
    DOMAIN_ROOT / "beatmap_legacy.py",
    DOMAIN_ROOT / "blob.py",
    DOMAIN_ROOT / "channel.py",
    DOMAIN_ROOT / "users" / "__init__.py",
    DOMAIN_ROOT / "users" / "events.py",
)

MOVED_DOMAIN_CONTEXT_ROOTS = (
    DOMAIN_ROOT / "beatmaps",
    DOMAIN_ROOT / "chat",
    DOMAIN_ROOT / "events",
    DOMAIN_ROOT / "storage",
)

FORBIDDEN_DOMAIN_IMPORT_ROOTS = (
    "osu_server.transports",
    "osu_server.repositories",
    "osu_server.infrastructure",
    "osu_server.services",
    "osu_server.jobs",
    "sqlalchemy",
    "taskiq",
    "starlette",
    "fastapi",
    "pydantic",
    "httpx",
    "aiohttp",
    "requests",
    "valkey",
)


def test_rehomed_domain_concepts_import_from_bounded_contexts() -> None:
    assert Beatmap.__name__ == "Beatmap"
    assert BeatmapResolveResult.__name__ == "BeatmapResolveResult"
    assert Channel.__name__ == "Channel"
    assert ChannelRoleOverride.__name__ == "ChannelRoleOverride"
    assert ChannelType.__name__ == "ChannelType"
    assert UserDisconnected.__name__ == "UserDisconnected"
    assert Blob.__name__ == "Blob"
    assert BlobStored.__name__ == "BlobStored"


def test_old_domain_concept_locations_are_not_supported() -> None:
    remaining = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in OLD_DOMAIN_CONCEPT_PATHS
        if path.exists()
    ]

    assert remaining == []


def test_moved_domain_contexts_have_no_adapter_or_io_imports() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {forbidden}"
        for root in MOVED_DOMAIN_CONTEXT_ROOTS
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
        for module in _imported_modules(path)
        for forbidden in FORBIDDEN_DOMAIN_IMPORT_ROOTS
        if _module_matches_root(module, forbidden)
    ]

    assert violations == []


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(
                f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
            )

    return modules


def _module_matches_root(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}.")
