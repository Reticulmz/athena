"""PP計算pathが将来scopeへ書き込まない境界契約を検証する."""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[6]
_SERVER_SOURCE_ROOT = Path("apps/athena_server/src")
_BOUNDARY_FILES = (
    _SERVER_SOURCE_ROOT / "osu_server/services/commands/scores/performance/request_calculation.py",
    _SERVER_SOURCE_ROOT / "osu_server/services/commands/scores/performance/execute_calculation.py",
    _SERVER_SOURCE_ROOT
    / "osu_server/services/commands/scores/performance/create_recalculation_batch.py",
    _SERVER_SOURCE_ROOT
    / "osu_server/services/commands/scores/performance/process_recalculation_batch.py",
    _SERVER_SOURCE_ROOT / "osu_server/infrastructure/performance/interfaces.py",
    _SERVER_SOURCE_ROOT / "osu_server/infrastructure/performance/rosu_calculator.py",
)
_PROJECTION_SCOPE_TERMS = (
    "leaderboard",
    "user_rank",
    "rank_projection",
)


def test_performance_boundary_audit_reads_server_owned_sources() -> None:
    """PP calculation静的監査がserver workspace sourceを読むことを検証する.

    Returns:
        None: 全boundary fileがserver productのphysical source owner配下にあることを検証する.
    """
    assert all(path.parts[:3] == ("apps", "athena_server", "src") for path in _BOUNDARY_FILES)


def test_performance_paths_do_not_update_unowned_projection_scopes() -> None:
    """計算performance pathが所有外projection scope用語を含まない契約を検証する.

    commandとcalculator interfaceのsourceを読む.
    leaderboardまたはrank projectionを示す用語がないことを確認する.

    Returns:
        None: 所有外scope用語の検出結果を検証して完了する.
    """
    matches: list[str] = []
    for relative_path in _BOUNDARY_FILES:
        source = (_PROJECT_ROOT / relative_path).read_text()
        matches.extend(
            f"{relative_path}:{term}" for term in _PROJECTION_SCOPE_TERMS if term in source
        )

    assert matches == []
