"""アーキテクチャ baseline の回帰契約を検証する."""

from importlib import import_module
from pathlib import Path

SERVER_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def test_di_runtime_dependencies_are_importable() -> None:
    """前提: DI runtime dependency が開発環境に存在する.

    操作: Dishka と Starlette の公開 integration package を import する.
    結果: 各 dependency の import が成功する.

    Returns:
        None: dependency import 契約を検証する.
    """
    assert import_module("dishka") is not None
    assert import_module("dishka.integrations.taskiq") is not None
    assert import_module("starlette_dishka") is not None


def test_architecture_guide_documents_refactor_boundaries() -> None:
    """前提: architecture guide が repository に配置されている.

    操作: guide の本文を読み必須 section と用語を照合する.
    結果: refactor boundary を示す全 section と用語が存在する.

    Returns:
        None: architecture documentation 契約を検証する.
    """
    architecture_guide = SERVER_WORKSPACE_ROOT / "docs" / "architecture.md"

    assert architecture_guide.exists()

    content = architecture_guide.read_text(encoding="utf-8")
    required_sections = [
        "# Athena Architecture",
        "## Layer Direction",
        "## Composition Responsibilities",
        "## Command And Query Use Cases",
        "## Persistence Boundaries And Unit Of Work",
        "## Domain Contexts",
        "## Compatibility Boundaries",
        "## Transport Families",
        "## Background Jobs",
        "## Placement Guide",
        "## Validation Contract",
    ]
    required_terms = [
        "Dishka",
        "APP scope",
        "REQUEST scope",
        "stable",
        "lazer",
        "first-party API",
        "command use-case",
        "query use-case",
        "Unit of Work",
        "domain/identity",
        "domain/compatibility/stable",
        "import-linter",
    ]

    for section in required_sections:
        assert section in content

    for term in required_terms:
        assert term in content
