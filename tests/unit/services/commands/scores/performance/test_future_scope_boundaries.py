"""Regression tests for PP calculation future-scope boundaries."""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[6]
_BOUNDARY_FILES = (
    Path("src/osu_server/services/commands/scores/process_submission.py"),
    Path("src/osu_server/services/commands/scores/performance/request_calculation.py"),
    Path("src/osu_server/services/commands/scores/performance/execute_calculation.py"),
    Path("src/osu_server/services/commands/scores/performance/create_recalculation_batch.py"),
    Path("src/osu_server/services/commands/scores/performance/process_recalculation_batch.py"),
    Path("src/osu_server/infrastructure/performance/interfaces.py"),
    Path("src/osu_server/infrastructure/performance/rosu_calculator.py"),
)
_PROJECTION_SCOPE_TERMS = (
    "leaderboard",
    "user_stats",
    "user_rank",
    "rank_projection",
)


def test_wave_2_performance_paths_do_not_update_future_projection_scopes() -> None:
    matches: list[str] = []
    for relative_path in _BOUNDARY_FILES:
        source = (_PROJECT_ROOT / relative_path).read_text()
        matches.extend(
            f"{relative_path}:{term}" for term in _PROJECTION_SCOPE_TERMS if term in source
        )

    assert matches == []
