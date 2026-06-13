from importlib import import_module
from pathlib import Path


def test_di_runtime_dependencies_are_importable() -> None:
    assert import_module("dishka") is not None
    assert import_module("dishka.integrations.taskiq") is not None
    assert import_module("starlette_dishka") is not None


def test_architecture_guide_documents_refactor_boundaries() -> None:
    architecture_guide = Path("docs/architecture.md")

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
