from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from athena_cli.commands import pp as pp_command
from athena_cli.main import app
from osu_server.composition import performance_cli
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceRecalculationBatch,
    PerformanceRecalculationBatchStatus,
    RecalculationCandidateReason,
)
from osu_server.domain.scores.score import Ruleset
from osu_server.services.commands.scores.performance import (
    CreatePerformanceRecalculationBatchCommand,
    CreatePerformanceRecalculationBatchMode,
    CreatePerformanceRecalculationBatchOutcome,
    CreatePerformanceRecalculationBatchResult,
)

runner = CliRunner()
_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


@dataclass(slots=True)
class StubRecalculationRunner:
    result: CreatePerformanceRecalculationBatchResult
    calls: list[tuple[str, CreatePerformanceRecalculationBatchCommand]] = field(
        default_factory=list
    )

    async def run(
        self,
        *,
        environment: str,
        command: CreatePerformanceRecalculationBatchCommand,
    ) -> CreatePerformanceRecalculationBatchResult:
        self.calls.append((environment, command))
        return self.result


def test_recalculate_defaults_to_dry_run_and_prints_candidate_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
            candidate_count=2,
            reason_counts={
                RecalculationCandidateReason.UNCALCULATED: 1,
                RecalculationCandidateReason.STALE: 1,
            },
            filters={
                "score_id": 10,
                "beatmap_id": None,
                "user_id": None,
                "ruleset": "osu",
                "limit": 25,
                "full_scope": False,
                "include_unavailable": False,
            },
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)
    monkeypatch.setattr(pp_command, "_now", lambda: _NOW)

    result = runner.invoke(
        app,
        [
            "pp",
            "recalculate",
            "--score-id",
            "10",
            "--ruleset",
            "osu",
            "--limit",
            "25",
            "--env",
            "test",
        ],
    )

    assert result.exit_code == 0
    assert "PP recalculation dry-run" in result.output
    assert "Candidates: 2" in result.output
    assert "uncalculated: 1" in result.output
    assert "stale: 1" in result.output
    assert len(stub.calls) == 1
    environment, command = stub.calls[0]
    assert environment == "test"
    assert command.mode is CreatePerformanceRecalculationBatchMode.DRY_RUN
    assert command.score_id == 10
    assert command.beatmap_id is None
    assert command.user_id is None
    assert command.ruleset is Ruleset.OSU
    assert command.limit == 25
    assert command.full_scope is False
    assert command.include_unavailable is False
    assert command.requested_at == _NOW


def test_recalculate_execute_prints_batch_id_and_candidate_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 6, 16, 12, 1, 0, tzinfo=UTC)
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.CREATED,
            candidate_count=1,
            reason_counts={RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH: 1},
            filters={
                "score_id": None,
                "beatmap_id": None,
                "user_id": 55,
                "ruleset": None,
                "limit": None,
                "full_scope": False,
                "include_unavailable": True,
            },
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            batch=PerformanceRecalculationBatch(
                id=42,
                status=PerformanceRecalculationBatchStatus.PENDING,
                filters={"user_id": 55},
                reason_counts={RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH: 1},
                target_calculator_version="4.0.2",
                target_formula_profile=FormulaProfile.VANILLA_RANKED,
                candidate_count=1,
                completed_count=0,
                unavailable_count=0,
                last_error=None,
                created_at=created_at,
                updated_at=created_at,
            ),
            worker_wake_requested=True,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)

    result = runner.invoke(
        app,
        [
            "pp",
            "recalculate",
            "--user-id",
            "55",
            "--include-unavailable",
            "--execute",
            "--env",
            "test",
        ],
    )

    assert result.exit_code == 0
    assert "PP recalculation batch created" in result.output
    assert "Batch ID: 42" in result.output
    assert "Candidates: 1" in result.output
    assert "calculator_version_mismatch: 1" in result.output
    assert len(stub.calls) == 1
    _, command = stub.calls[0]
    assert command.mode is CreatePerformanceRecalculationBatchMode.EXECUTE
    assert command.user_id == 55
    assert command.include_unavailable is True


def test_recalculate_without_filter_requires_all_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
            candidate_count=0,
            reason_counts={},
            filters={},
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)

    result = runner.invoke(app, ["pp", "recalculate", "--env", "test"])

    assert result.exit_code == 2
    assert "Use --all or a narrow filter for full-scope recalculation." in result.output
    assert stub.calls == []


def test_execute_without_filter_requires_all_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.CREATED,
            candidate_count=0,
            reason_counts={},
            filters={},
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)

    result = runner.invoke(app, ["pp", "recalculate", "--execute", "--env", "test"])

    assert result.exit_code == 2
    assert "Use --all or a narrow filter for full-scope recalculation." in result.output
    assert stub.calls == []


def test_limit_without_filter_requires_all_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
            candidate_count=0,
            reason_counts={},
            filters={},
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)

    result = runner.invoke(app, ["pp", "recalculate", "--limit", "10", "--env", "test"])

    assert result.exit_code == 2
    assert "Use --all or a narrow filter for full-scope recalculation." in result.output
    assert stub.calls == []


def test_all_flag_cannot_be_combined_with_narrow_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
            candidate_count=0,
            reason_counts={},
            filters={},
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)

    result = runner.invoke(
        app,
        ["pp", "recalculate", "--all", "--score-id", "10", "--env", "test"],
    )

    assert result.exit_code == 2
    assert "Cannot combine --all with score, beatmap, user, or ruleset filters." in result.output
    assert stub.calls == []


def test_recalculate_rejects_invalid_ruleset(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
            candidate_count=0,
            reason_counts={},
            filters={},
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)

    result = runner.invoke(app, ["pp", "recalculate", "--ruleset", "ctb"])

    assert result.exit_code == 2
    assert "Unsupported ruleset 'ctb'. Supported rulesets: osu, taiko, catch, mania." in (
        result.output
    )
    assert stub.calls == []


@pytest.mark.parametrize(
    ("option", "message"),
    [
        ("--score-id", "score id must be positive."),
        ("--beatmap-id", "beatmap id must be positive."),
        ("--user-id", "user id must be positive."),
        ("--limit", "limit must be positive."),
    ],
)
def test_recalculate_rejects_non_positive_numeric_filters(
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    message: str,
) -> None:
    stub = StubRecalculationRunner(
        CreatePerformanceRecalculationBatchResult(
            outcome=CreatePerformanceRecalculationBatchOutcome.DRY_RUN,
            candidate_count=0,
            reason_counts={},
            filters={},
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
        )
    )
    monkeypatch.setattr(pp_command, "create_recalculation_runner", lambda: stub)

    result = runner.invoke(app, ["pp", "recalculate", option, "0"])

    assert result.exit_code == 2
    assert message in result.output
    assert stub.calls == []


def test_pp_cli_command_does_not_import_calculator_or_raw_sql() -> None:
    source = inspect.getsource(pp_command)
    tree = ast.parse(source)

    assert "rosu_pp_py" not in source
    assert "rosu_calculator" not in source
    assert "RosuPerformanceCalculator" not in source
    assert not _imports_module(tree, "sqlalchemy")
    assert not _calls_function(tree, "text")


def test_pp_cli_composition_does_not_import_calculator_or_raw_sql() -> None:
    source = inspect.getsource(performance_cli)
    tree = ast.parse(source)

    assert "rosu_pp_py" not in source
    assert "rosu_calculator" not in source
    assert "RosuPerformanceCalculator" not in source
    assert not _calls_function(tree, "text")


def test_pp_cli_command_import_does_not_load_calculator_runtime() -> None:
    script = (
        "import sys; "
        "import athena_cli.commands.pp; "
        "modules = [name for name in sys.modules if 'rosu' in name]; "
        "print(modules); "
        "raise SystemExit(1 if modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def _imports_module(tree: ast.AST, module_name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == module_name or alias.name.startswith(f"{module_name}.")
            for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == module_name or module.startswith(f"{module_name}."):
                return True
    return False


def _calls_function(tree: ast.AST, function_name: str) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == function_name
        ):
            return True
    return False
