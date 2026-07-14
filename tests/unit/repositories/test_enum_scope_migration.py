import ast
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, Column, Table, UniqueConstraint
from sqlalchemy import Enum as SQLAlchemyEnum

from osu_server.repositories.sqlalchemy.models import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapLeaderboardUserBestModel,
    BeatmapModel,
    BeatmapSetModel,
    BlobModel,
    ChannelModel,
    PerformanceRecalculationBatchModel,
    PerformanceRecalculationWorkItemModel,
    PersonalBestModel,
    ScoreModel,
    ScorePerformanceCalculationModel,
    ScoreSubmissionModel,
)


def _find_repository_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "alembic.ini").is_file():
            return candidate
    msg = f"repository root not found from {start}"
    raise RuntimeError(msg)


_REPOSITORY_ROOT = _find_repository_root(Path(__file__).resolve().parent)
MIGRATION_PATH = Path(
    "alembic/versions/20260710_0400_use_enum_types_and_score_based_leaderboards.py"
)
LEADERBOARD_REPAIR_MIGRATION_PATH = Path(
    "alembic/versions/20260712_0500_repair_legacy_leaderboard_projection.py"
)
MOD_SCOPED_MIGRATION_PATH = Path(
    "alembic/versions/20260713_0600_add_mod_scoped_leaderboard_projection.py"
)
ONLINE_INDEX_MIGRATION_PATH = Path(
    "alembic/versions/20260713_0700_create_leaderboard_indexes_concurrently.py"
)


def _migration_tree(path: Path) -> ast.Module:
    resolved_path = path if path.is_absolute() else _REPOSITORY_ROOT / path
    return ast.parse(
        resolved_path.read_text(encoding="utf-8"),
        filename=resolved_path.as_posix(),
    )


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    function = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name),
        None,
    )
    if function is None:
        msg = f"missing top-level function: {name}"
        raise AssertionError(msg)
    return function


def _top_level_assignment_value(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return node.value
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
    msg = f"missing top-level assignment: {name}"
    raise AssertionError(msg)


def _top_level_assignment_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return names


def _string_assignment(tree: ast.Module, name: str) -> str:
    value = _top_level_assignment_value(tree, name)
    assert isinstance(value, ast.Constant)
    assert isinstance(value.value, str)
    return value.value


def _assigned_call(tree: ast.Module, name: str) -> ast.Call:
    value = _top_level_assignment_value(tree, name)
    assert isinstance(value, ast.Call)
    return value


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        return _qualified_name(node.func)
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return node.attr if parent is None else f"{parent}.{node.attr}"
    return None


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for imported in node.names:
                if imported.asname is not None:
                    aliases[imported.asname] = imported.name
                    continue
                root_name = imported.name.split(".", maxsplit=1)[0]
                aliases[root_name] = root_name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            for imported in node.names:
                if imported.name == "*":
                    continue
                local_name = imported.asname or imported.name
                aliases[local_name] = f"{node.module}.{imported.name}"
    return aliases


def _resolved_name(name: str, aliases: dict[str, str]) -> str:
    root_name, separator, remainder = name.partition(".")
    resolved_root = aliases.get(root_name, root_name)
    return resolved_root if not separator else f"{resolved_root}.{remainder}"


def _calls_named(node: ast.AST, name: str) -> tuple[ast.Call, ...]:
    return tuple(
        candidate
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Call) and _qualified_name(candidate.func) == name
    )


def _calls_resolved_as(
    tree: ast.Module,
    node: ast.AST,
    canonical_name: str,
) -> tuple[ast.Call, ...]:
    aliases = _import_aliases(tree)
    return tuple(
        candidate
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Call)
        and (qualified_name := _qualified_name(candidate.func)) is not None
        and _resolved_name(qualified_name, aliases) == canonical_name
    )


def _direct_call_names(function: ast.FunctionDef) -> tuple[str, ...]:
    names: list[str] = []
    for statement in function.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        name = _qualified_name(statement.value.func)
        if name is not None:
            names.append(name)
    return tuple(names)


def _keyword_expression(call: ast.Call, name: str) -> ast.expr:
    value = next((keyword.value for keyword in call.keywords if keyword.arg == name), None)
    if value is None:
        msg = f"missing keyword {name} on {_qualified_name(call.func)}"
        raise AssertionError(msg)
    return value


def _boolean_keyword(call: ast.Call, name: str) -> bool:
    value = _keyword_expression(call, name)
    assert isinstance(value, ast.Constant)
    assert isinstance(value.value, bool)
    return value.value


def _string_keyword(call: ast.Call, name: str) -> str:
    value = _keyword_expression(call, name)
    assert isinstance(value, ast.Constant)
    assert isinstance(value.value, str)
    return value.value


def _string_sequence_argument(call: ast.Call, index: int) -> tuple[str, ...]:
    value = call.args[index]
    assert isinstance(value, (ast.List, ast.Tuple))
    items: list[str] = []
    for item in value.elts:
        assert isinstance(item, ast.Constant)
        assert isinstance(item.value, str)
        items.append(item.value)
    return tuple(items)


def _has_autocommit_block(tree: ast.Module, function: ast.FunctionDef) -> bool:
    aliases = _import_aliases(tree)
    return any(
        isinstance(node, (ast.With, ast.AsyncWith))
        and any(
            (qualified_name := _qualified_name(item.context_expr)) is not None
            and _resolved_name(qualified_name, aliases)
            == "alembic.op.get_context.autocommit_block"
            for item in node.items
        )
        for node in ast.walk(function)
    )


def _assert_index_operations_are_concurrent(
    tree: ast.Module,
    function: ast.FunctionDef,
) -> None:
    index_calls = (
        *_calls_resolved_as(tree, function, "alembic.op.create_index"),
        *_calls_resolved_as(tree, function, "alembic.op.drop_index"),
    )
    assert index_calls
    assert all(_boolean_keyword(call, "postgresql_concurrently") for call in index_calls)


def _assert_no_calls(tree: ast.Module, *canonical_names: str) -> None:
    for canonical_name in canonical_names:
        assert _calls_resolved_as(tree, tree, canonical_name) == ()


def _assert_check_constraints_are_structural(tree: ast.Module) -> None:
    for call in _calls_resolved_as(tree, tree, "sqlalchemy.CheckConstraint"):
        assert call.args
        predicate = call.args[0]
        assert not (isinstance(predicate, ast.Constant) and isinstance(predicate.value, str))


def test_migration_tree_resolves_relative_path_from_repository_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """migration pathがpytest起動時のCWDに依存しないことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): test processのCWDを一時変更するfixture.
        tmp_path (Path): repository外の一時working directory.

    Returns:
        None: repository外からrelative migration pathを解析できたことを示す.

    Raises:
        AssertionError: repository root解決またはrevision解析が失敗した場合.
    """
    monkeypatch.chdir(tmp_path)

    tree = _migration_tree(MIGRATION_PATH)

    assert _string_assignment(tree, "revision") == "20260710_0400"


@pytest.mark.parametrize(
    ("source", "canonical_name"),
    [
        pytest.param(
            "from sqlalchemy import text\ntext('select current_date')",
            "sqlalchemy.text",
            id="direct-import",
        ),
        pytest.param(
            "from sqlalchemy import text as sql_text\nsql_text('select current_date')",
            "sqlalchemy.text",
            id="aliased-direct-import",
        ),
        pytest.param(
            "import sqlalchemy as database\ndatabase.text('select current_date')",
            "sqlalchemy.text",
            id="aliased-module-import",
        ),
        pytest.param(
            "from sqlalchemy import delete as remove\nremove('scores')",
            "sqlalchemy.delete",
            id="delete-alias",
        ),
        pytest.param(
            "from sqlalchemy.dialects.postgresql import ENUM as PgEnum\nPgEnum('state')",
            "sqlalchemy.dialects.postgresql.ENUM",
            id="postgresql-enum-alias",
        ),
    ],
)
def test_banned_call_detection_resolves_import_aliases(
    source: str,
    canonical_name: str,
) -> None:
    """禁止SQLAlchemy APIがdirect importとalias経由でも検出されることを検証する.

    Args:
        source (str): 禁止API呼び出しを含むsynthetic Python source.
        canonical_name (str): import解決後に拒否する完全修飾API名.

    Returns:
        None: alias解決後の禁止callがassertion failureになったことを示す.

    Raises:
        AssertionError: 禁止callを検出できない場合.
    """
    tree = ast.parse(source)

    with pytest.raises(AssertionError):
        _assert_no_calls(tree, canonical_name)


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _enum_type(table: Table, column_name: str) -> SQLAlchemyEnum:
    enum_type = _column(table, column_name).type
    assert isinstance(enum_type, SQLAlchemyEnum)
    return enum_type


def _assert_checked_string_enum(
    table: Table,
    column_name: str,
    constraint_name: str,
    length: int,
) -> None:
    enum_type = _enum_type(table, column_name)
    assert cast("bool", enum_type.native_enum) is False
    assert cast("bool", enum_type.create_constraint) is True
    assert cast("bool", enum_type.validate_strings) is True
    assert enum_type.name == constraint_name
    assert enum_type.length == length
    assert any(
        isinstance(constraint, CheckConstraint) and constraint.name == constraint_name
        for constraint in table.constraints
    )


def test_enum_migration_converts_closed_values_and_score_based_leaderboards() -> None:
    """migrationがCHECK付き文字列Enumとscore正本leaderboardを定義することを確認する.

    Returns:
        None: migration sourceの必須構造が存在することを示す.

    Raises:
        AssertionError: revision, Enum制約, またはleaderboard構造が不足する場合.

    Notes:
        PostgreSQLでの実動作はintegration migration testで別途検証する.
    """
    tree = _migration_tree(MIGRATION_PATH)

    assert _string_assignment(tree, "revision") == "20260710_0400"
    assert _string_assignment(tree, "down_revision") == "20260710_0300"
    checked_enum_helper = _top_level_function(tree, "_checked_string_enum")
    enum_call = _calls_resolved_as(tree, checked_enum_helper, "sqlalchemy.Enum")
    assert len(enum_call) == 1
    assert _boolean_keyword(enum_call[0], "native_enum") is False
    assert _boolean_keyword(enum_call[0], "create_constraint") is True
    assert _boolean_keyword(enum_call[0], "validate_strings") is True
    assert _qualified_name(_keyword_expression(enum_call[0], "length")) == "length"

    enum_constraints = {
        "PLAY_TIME_SOURCE_ENUM": "ck_scores_play_time_source_known",
        "BEATMAP_MODE_ENUM": "ck_beatmaps_mode_known",
        "BEATMAP_FETCH_TARGET_KIND_ENUM": "ck_beatmap_fetch_states_target_type_known",
        "BLOB_STORAGE_BACKEND_ENUM": "ck_blobs_storage_backend_known",
        "SCORE_SUBMISSION_STATE_ENUM": "ck_score_submissions_state_known",
        "PERFORMANCE_CALCULATION_STATE_ENUM": "ck_score_performance_state_known",
    }
    for assignment, constraint_name in enum_constraints.items():
        call = _assigned_call(tree, assignment)
        assert _qualified_name(call.func) == "_checked_string_enum"
        assert _string_keyword(call, "name") == constraint_name

    upgrade_calls = _direct_call_names(_top_level_function(tree, "upgrade"))
    assert upgrade_calls[-1] == "_upgrade_leaderboard_storage"
    upgrade_storage_calls = _direct_call_names(
        _top_level_function(tree, "_upgrade_leaderboard_storage")
    )
    assert upgrade_storage_calls[0] == "lock_projection_updates"
    assert upgrade_storage_calls[-1] == "_replace_projection_table"
    downgrade_storage_calls = _direct_call_names(
        _top_level_function(tree, "_downgrade_leaderboard_storage")
    )
    assert downgrade_storage_calls[0] == "lock_projection_updates"
    assert downgrade_storage_calls[-1] == "_replace_projection_table"
    assert _string_assignment(tree, "_GLOBAL_PROJECTION_STAGING_TABLE")
    assert _string_assignment(tree, "_LEGACY_PROJECTION_STAGING_TABLE")

    function_names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {
        "_validate_enum_column",
        "_create_enum_constraint",
        "_drop_enum_constraint",
    } <= function_names
    assert "_ENUM_TYPES" not in _top_level_assignment_names(tree)
    assert not any(
        keyword.arg == "postgresql_using"
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
    )
    _assert_no_calls(
        tree,
        "sqlalchemy.delete",
        "sqlalchemy.text",
        "sqlalchemy.dialects.postgresql.ENUM",
    )
    _assert_check_constraints_are_structural(tree)


def test_enum_constraints_are_added_not_valid_before_explicit_scan() -> None:
    """Enum CHECK追加時の長時間table scanがwriteを遮断しないことを確認する.

    Returns:
        None: NOT VALID追加後に既存値を明示検証する構造であることを示す.

    Raises:
        AssertionError: CHECK追加が既存値scanを伴う場合, または検証順が逆の場合.
    """
    tree = _migration_tree(MIGRATION_PATH)
    helper = _top_level_function(tree, "_create_enum_constraint")
    constraint_calls = _calls_resolved_as(
        tree,
        helper,
        "alembic.op.create_check_constraint",
    )
    validation_calls = _calls_named(helper, "_validate_enum_column")

    assert len(constraint_calls) == 1
    assert len(validation_calls) == 1
    assert _boolean_keyword(constraint_calls[0], "postgresql_not_valid") is True
    assert constraint_calls[0].lineno < validation_calls[0].lineno


def test_legacy_projection_repair_builds_staging_before_swap() -> None:
    """0500 fallbackがlive tableを保持したままbackfillすることを確認する.

    Returns:
        None: staging作成, backfill, 最終swapの順序を満たすことを示す.

    Raises:
        AssertionError: live tableをbackfill前にdropする修復構造の場合.
    """
    tree = _migration_tree(LEADERBOARD_REPAIR_MIGRATION_PATH)
    repair = _top_level_function(tree, "_recreate_global_projection")
    calls = _direct_call_names(repair)

    assert _string_assignment(tree, "_PROJECTION_STAGING_TABLE")
    assert calls[0] == "lock_projection_updates"
    assert "_create_global_projection_table" in calls
    assert calls.index("_rebuild_current_global_projection") < calls.index(
        "_replace_projection_table"
    )
    assert calls[-1] == "_replace_projection_table"


def test_legacy_mod_filter_restoration_is_used_only_for_0400_downgrade() -> None:
    """旧mod_filter_key復元が0400 downgradeだけに閉じることを確認する.

    Returns:
        None: 旧projection復元からdowngradeまでのcall chainを確認したことを示す.

    Raises:
        AssertionError: 旧projection復元がupgrade pathから参照される場合.
    """
    migration_tree = _migration_tree(MIGRATION_PATH)
    callers_by_callee: dict[str, set[str]] = {}
    for node in ast.walk(migration_tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for candidate in ast.walk(node):
            if isinstance(candidate, ast.Call) and isinstance(candidate.func, ast.Name):
                callers_by_callee.setdefault(candidate.func.id, set()).add(node.name)

    assert callers_by_callee.get("_restore_legacy_leaderboard_projection", set()) == {
        "_downgrade_leaderboard_storage"
    }
    assert callers_by_callee.get("_downgrade_leaderboard_storage", set()) == {"downgrade"}


def test_mod_scoped_projection_migration_uses_checked_raw_mod_bitflags() -> None:
    """0600 migrationがraw Mod単位のprojection schemaを定義することを確認する.

    Returns:
        None: migration sourceのschema, backfill, index定義が一致したことを示す.

    Raises:
        AssertionError: revisionまたはMod単位projectionの必須構造が不足する場合.
    """
    tree = _migration_tree(MOD_SCOPED_MIGRATION_PATH)

    assert _string_assignment(tree, "revision") == "20260713_0600"
    assert _string_assignment(tree, "down_revision") == "20260712_0500"
    assert _string_assignment(tree, "_MODS_CHECK_CONSTRAINT") == (
        "ck_beatmap_leaderboard_user_bests_mods_non_negative"
    )
    assert _string_assignment(tree, "_MOD_SCOPED_PROJECTION_STAGING_TABLE")
    assert _string_assignment(tree, "_GLOBAL_PROJECTION_STAGING_TABLE")

    upgrade = _top_level_function(tree, "upgrade")
    upgrade_calls = _direct_call_names(upgrade)
    assert upgrade_calls[0] == "lock_projection_updates"
    assert upgrade_calls[-1] == "_replace_projection_table"
    upgrade_rebuild = _calls_named(upgrade, "_rebuild_projection")
    assert len(upgrade_rebuild) == 1
    assert _boolean_keyword(upgrade_rebuild[0], "partition_by_mods") is True

    downgrade = _top_level_function(tree, "downgrade")
    downgrade_calls = _direct_call_names(downgrade)
    assert downgrade_calls[0] == "lock_projection_updates"
    assert downgrade_calls[-1] == "_replace_projection_table"
    downgrade_rebuild = _calls_named(downgrade, "_rebuild_projection")
    assert len(downgrade_rebuild) == 1
    assert _boolean_keyword(downgrade_rebuild[0], "partition_by_mods") is False

    create_table = _top_level_function(tree, "_create_mod_scoped_projection_table")
    mods_column = next(
        call
        for call in _calls_resolved_as(tree, create_table, "sqlalchemy.Column")
        if call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == "mods"
    )
    mods_type_name = _qualified_name(mods_column.args[1])
    assert mods_type_name is not None
    assert _resolved_name(mods_type_name, _import_aliases(tree)) == "sqlalchemy.Integer"
    assert _boolean_keyword(mods_column, "nullable") is False

    unique_scope_columns = {
        _string_sequence_argument(call, 2)
        for call in _calls_resolved_as(tree, upgrade, "alembic.op.create_unique_constraint")
    }
    assert (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "user_id",
        "mods",
    ) in unique_scope_columns
    rebuild = _top_level_function(tree, "_rebuild_projection")
    assert any(
        call.args and _qualified_name(call.args[0]) == "scores.c.mods"
        for call in _calls_named(rebuild, "partition_columns.append")
    )
    assert "_delete_projection_rows" not in {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    _assert_no_calls(tree, "sqlalchemy.text")
    _assert_check_constraints_are_structural(tree)


def test_leaderboard_indexes_are_created_concurrently_without_raw_sql() -> None:
    """Leaderboard index migrationがonline DDLだけを使用することを確認する.

    Returns:
        None: 0500 candidateと0700 read indexがconcurrent作成されることを示す.

    Raises:
        AssertionError: autocommit, concurrent指定, またはAlembic API利用が不足する場合.
    """
    enum_tree = _migration_tree(MIGRATION_PATH)
    repair_tree = _migration_tree(LEADERBOARD_REPAIR_MIGRATION_PATH)
    online_index_tree = _migration_tree(ONLINE_INDEX_MIGRATION_PATH)

    assert "_SCORE_CANDIDATE_INDEX" not in _top_level_assignment_names(enum_tree)
    repair_index = _top_level_function(repair_tree, "_recreate_score_candidate_index")
    assert _has_autocommit_block(repair_tree, repair_index)
    _assert_index_operations_are_concurrent(repair_tree, repair_index)
    repair_projection_calls = _direct_call_names(
        _top_level_function(repair_tree, "_recreate_global_projection")
    )
    assert repair_projection_calls[0] == "lock_projection_updates"

    assert _string_assignment(online_index_tree, "revision") == "20260713_0700"
    assert _string_assignment(online_index_tree, "down_revision") == "20260713_0600"
    assert _has_autocommit_block(
        online_index_tree,
        _top_level_function(online_index_tree, "upgrade"),
    )
    assert _has_autocommit_block(
        online_index_tree,
        _top_level_function(online_index_tree, "downgrade"),
    )
    for function_name in (
        "_repair_score_candidate_index",
        "_drop_rank_indexes",
        "_create_rank_indexes",
    ):
        _assert_index_operations_are_concurrent(
            online_index_tree,
            _top_level_function(online_index_tree, function_name),
        )
    assert _string_assignment(online_index_tree, "_SCORE_CANDIDATE_INDEX") == (
        "idx_scores_beatmap_leaderboard_candidates"
    )
    assert _string_assignment(online_index_tree, "_GLOBAL_RANK_INDEX") == (
        "idx_beatmap_leaderboard_user_bests_global_rank"
    )
    assert _string_assignment(online_index_tree, "_MOD_RANK_INDEX") == (
        "idx_beatmap_leaderboard_user_bests_mod_rank"
    )
    _assert_no_calls(repair_tree, "sqlalchemy.text")
    _assert_no_calls(online_index_tree, "sqlalchemy.text")


def test_current_models_use_checked_string_enums_for_closed_value_columns() -> None:
    """閉集合カラムが非native Enumと名前付きCHECKを使用することを検証する.

    Returns:
        None: 全対象カラムの型と制約を検証したことを示す.

    Raises:
        AssertionError: native Enum、CHECK未作成、または制約名不一致の場合.
    """
    cases = (
        (ChannelModel.__table__, "channel_type", "ck_channels_channel_type_known", 16),
        (ScoreModel.__table__, "grade", "ck_scores_grade_known", 2),
        (
            ScoreModel.__table__,
            "beatmap_status_at_submission",
            "ck_beatmap_rank_status_known",
            32,
        ),
        (
            ScoreModel.__table__,
            "play_time_source",
            "ck_scores_play_time_source_known",
            32,
        ),
        (
            ScoreSubmissionModel.__table__,
            "state",
            "ck_score_submissions_state_known",
            32,
        ),
        (
            BeatmapSetModel.__table__,
            "official_status",
            "ck_beatmap_rank_status_known",
            32,
        ),
        (
            BeatmapSetModel.__table__,
            "official_status_source",
            "ck_beatmap_metadata_source_known",
            64,
        ),
        (BeatmapModel.__table__, "mode", "ck_beatmaps_mode_known", 16),
        (
            BeatmapModel.__table__,
            "official_status",
            "ck_beatmap_rank_status_known",
            32,
        ),
        (
            BeatmapModel.__table__,
            "official_status_source",
            "ck_beatmap_metadata_source_known",
            64,
        ),
        (
            BeatmapModel.__table__,
            "local_status_override",
            "ck_beatmaps_local_status_override_known",
            32,
        ),
        (
            BeatmapFileAttachmentModel.__table__,
            "source",
            "ck_beatmap_file_attachments_source_known",
            32,
        ),
        (
            BeatmapFetchStateModel.__table__,
            "target_type",
            "ck_beatmap_fetch_states_target_type_known",
            32,
        ),
        (
            BeatmapFetchStateModel.__table__,
            "status",
            "ck_beatmap_fetch_states_status_known",
            32,
        ),
        (BlobModel.__table__, "storage_backend", "ck_blobs_storage_backend_known", 32),
        (
            PersonalBestModel.__table__,
            "category",
            "ck_personal_bests_category_known",
            32,
        ),
        (
            ScorePerformanceCalculationModel.__table__,
            "state",
            "ck_score_performance_state_known",
            32,
        ),
        (
            ScorePerformanceCalculationModel.__table__,
            "formula_profile",
            "ck_formula_profile_known",
            64,
        ),
        (
            PerformanceRecalculationBatchModel.__table__,
            "status",
            "ck_performance_recalculation_batches_status_known",
            32,
        ),
        (
            PerformanceRecalculationBatchModel.__table__,
            "target_formula_profile",
            "ck_formula_profile_known",
            64,
        ),
        (
            PerformanceRecalculationWorkItemModel.__table__,
            "reason",
            "ck_performance_recalculation_work_items_reason_known",
            64,
        ),
        (
            PerformanceRecalculationWorkItemModel.__table__,
            "state",
            "ck_performance_recalculation_work_items_state_known",
            32,
        ),
    )

    for table, column_name, constraint_name, length in cases:
        _assert_checked_string_enum(
            cast("Table", table),
            column_name,
            constraint_name,
            length,
        )


def test_current_leaderboard_projection_is_mod_scoped_and_score_unique() -> None:
    table = cast("Table", BeatmapLeaderboardUserBestModel.__table__)
    unique_constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "mod_filter_key" not in table.c
    assert not _column(table, "mods").nullable
    unique_scope = unique_constraints["uq_beatmap_leaderboard_user_bests_scope"]
    assert tuple(column.name for column in unique_scope.columns) == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "user_id",
        "mods",
    )
    unique_score = unique_constraints["uq_beatmap_leaderboard_user_bests_score_id"]
    assert tuple(column.name for column in unique_score.columns) == ("score_id",)
