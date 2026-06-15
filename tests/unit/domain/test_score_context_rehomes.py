"""Score bounded-context ownership tests."""

from __future__ import annotations

import ast
from pathlib import Path

from osu_server.domain.scores import (
    DecryptedPayload,
    Grade,
    ParsedScore,
    ParseError,
    Playstyle,
    Replay,
    Ruleset,
    Score,
    ScoreSubmission,
    ValidationError,
    ValidationResult,
    validate_hit_counts,
)

PROJECT_ROOT = Path(__file__).parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"
TEST_ROOT = PROJECT_ROOT / "tests"
DOMAIN_ROOT = SOURCE_ROOT / "domain"
DEPRECATED_IMPORT_BASELINE = (
    PROJECT_ROOT / "tests" / "fixtures" / "architecture" / "deprecated_imports.txt"
)

OLD_SCORE_CONTEXT_PATHS = (
    DOMAIN_ROOT / "score" / "__init__.py",
    DOMAIN_ROOT / "score" / "decryption.py",
    DOMAIN_ROOT / "score" / "payload_parser.py",
    DOMAIN_ROOT / "score" / "replay.py",
    DOMAIN_ROOT / "score" / "score.py",
    DOMAIN_ROOT / "score" / "submission.py",
    DOMAIN_ROOT / "score" / "validator.py",
)

CROSS_LAYER_AND_TEST_ROOTS = (
    SOURCE_ROOT / "repositories",
    SOURCE_ROOT / "services",
    SOURCE_ROOT / "transports",
    SOURCE_ROOT / "jobs",
    TEST_ROOT,
)

DEPRECATED_SCORE_IMPORT_ROOT = "osu_server.domain.score"


def test_score_domain_concepts_import_from_scores_context() -> None:
    assert DecryptedPayload.__name__ == "DecryptedPayload"
    assert ParsedScore.__name__ == "ParsedScore"
    assert ParseError.__name__ == "ParseError"
    assert Replay.__name__ == "Replay"
    assert Grade.__name__ == "Grade"
    assert Playstyle.__name__ == "Playstyle"
    assert Ruleset.__name__ == "Ruleset"
    assert Score.__name__ == "Score"
    assert ScoreSubmission.__name__ == "ScoreSubmission"
    assert ValidationError.__name__ == "ValidationError"
    assert ValidationResult.__name__ == "ValidationResult"
    assert validate_hit_counts.__name__ == "validate_hit_counts"


def test_old_score_context_locations_are_not_supported() -> None:
    remaining = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in OLD_SCORE_CONTEXT_PATHS
        if path.exists()
    ]

    assert remaining == []


def test_cross_layer_and_tests_do_not_import_old_score_context() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for root in CROSS_LAYER_AND_TEST_ROOTS
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
        for module in _imported_modules(path)
        if _module_matches_root(module, DEPRECATED_SCORE_IMPORT_ROOT)
    ]

    assert violations == []


def test_deprecated_import_baseline_has_no_old_score_context() -> None:
    entries = DEPRECATED_IMPORT_BASELINE.read_text(encoding="utf-8").splitlines()
    roots = [entry.split("\t", maxsplit=1)[1] for entry in entries if entry and "\t" in entry]

    assert all(not _module_matches_root(root, DEPRECATED_SCORE_IMPORT_ROOT) for root in roots)


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
