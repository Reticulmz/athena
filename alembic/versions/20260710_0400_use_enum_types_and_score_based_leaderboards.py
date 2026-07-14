"""CHECK付き文字列Enumとscore正本のleaderboard filterを導入するmigration.

Revision ID: 20260710_0400
Revises: 20260710_0300
Create Date: 2026-07-10 01:00:00.000000
"""

from __future__ import annotations

from hashlib import blake2b
from typing import TYPE_CHECKING, cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260710_0400"
down_revision: str | None = "20260710_0300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# pre-0400 downgrade互換専用. 現行schemaはraw Mod bitmaskを変更せず保存する.
_LEGACY_NIGHTCORE_BIT = 1 << 9
_LEGACY_DOUBLE_TIME_BIT = 1 << 6
_LEGACY_PERFECT_BIT = 1 << 14
_LEGACY_SUDDEN_DEATH_BIT = 1 << 5
_LEGACY_MIRROR_BIT = 1 << 30
_LEGACY_PREFERENCE_ONLY_NO_MODS_BITS = (
    _LEGACY_SUDDEN_DEATH_BIT | _LEGACY_PERFECT_BIT | _LEGACY_MIRROR_BIT
)
_PROJECTION_TABLE = "beatmap_leaderboard_user_bests"
_GLOBAL_PROJECTION_STAGING_TABLE = "_beatmap_leaderboard_user_bests_0400_global"
_LEGACY_PROJECTION_STAGING_TABLE = "_beatmap_leaderboard_user_bests_0400_legacy"
_GLOBAL_SCOPE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_global_scope_0400"
_GLOBAL_SCORE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_global_score_id_0400"
_GLOBAL_SCORE_FOREIGN_KEY = "fk_beatmap_leaderboard_user_bests_global_score_id_0400"
_GLOBAL_USER_REBUILD_INDEX = "idx_beatmap_leaderboard_user_bests_global_user_rebuild_0400"
_LEGACY_MODS_CHECK_CONSTRAINT = "ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative"
_LEGACY_SCORE_FOREIGN_KEY = "fk_beatmap_leaderboard_user_bests_score_id"
_LEGACY_SCOPE_UNIQUE_INDEX = "idx_beatmap_leaderboard_user_bests_scope_unique"
_LEGACY_ORDERING_INDEX = "idx_beatmap_leaderboard_user_bests_ordering"
_LEGACY_USER_REBUILD_INDEX = "idx_beatmap_leaderboard_user_bests_user_rebuild"
_PROJECTION_REBUILD_LOCK_NAMESPACE = "beatmap_leaderboard_user_bests:rebuild"


def _checked_string_enum(
    *values: str,
    name: str,
    length: int,
) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=length,
    )


BEATMAP_FETCH_STATE_ENUM = _checked_string_enum(
    "fresh",
    "stale",
    "pending_fetch",
    "failed",
    name="ck_beatmap_fetch_states_status_known",
    length=32,
)
BEATMAP_FETCH_TARGET_KIND_ENUM = _checked_string_enum(
    "metadata:beatmap",
    "metadata:beatmapset",
    "metadata:checksum",
    "file:beatmap",
    name="ck_beatmap_fetch_states_target_type_known",
    length=32,
)
BEATMAP_FILE_SOURCE_ENUM = _checked_string_enum(
    "official",
    "legacy_official",
    "mirror",
    "osu_current",
    "osu_legacy",
    "community_mirror",
    "archive_extracted",
    name="ck_beatmap_file_attachments_source_known",
    length=32,
)
BEATMAP_METADATA_SOURCE_ENUM = _checked_string_enum(
    "official",
    "legacy_official",
    "mirror",
    name="ck_beatmap_metadata_source_known",
    length=64,
)
BEATMAP_MODE_ENUM = _checked_string_enum(
    "osu",
    "taiko",
    "fruits",
    "mania",
    "unknown",
    name="ck_beatmaps_mode_known",
    length=16,
)
BEATMAP_RANK_STATUS_ENUM = _checked_string_enum(
    "ranked",
    "approved",
    "loved",
    "qualified",
    "pending",
    "wip",
    "graveyard",
    "not_submitted",
    "unknown",
    name="ck_beatmap_rank_status_known",
    length=32,
)
BLOB_STORAGE_BACKEND_ENUM = _checked_string_enum(
    "local",
    "s3",
    name="ck_blobs_storage_backend_known",
    length=32,
)
CHANNEL_TYPE_ENUM = _checked_string_enum(
    "public",
    "multiplayer",
    "spectator",
    "temporary",
    name="ck_channels_channel_type_known",
    length=16,
)
FORMULA_PROFILE_ENUM = _checked_string_enum(
    "vanilla_ranked_legacy",
    "vanilla_ranked_v1",
    name="ck_formula_profile_known",
    length=64,
)
LEADERBOARD_CATEGORY_ENUM = _checked_string_enum(
    "global",
    "country",
    "selected_mods",
    "friends",
    name="ck_personal_bests_category_known",
    length=32,
)
LOCAL_BEATMAP_STATUS_ENUM = _checked_string_enum(
    "ranked",
    "loved",
    "qualified",
    "pending",
    "wip",
    "graveyard",
    "not_submitted",
    "unknown",
    name="ck_beatmaps_local_status_override_known",
    length=32,
)
PERFORMANCE_CALCULATION_STATE_ENUM = _checked_string_enum(
    "queued",
    "fetching_file",
    "calculating",
    "completed",
    "unavailable",
    "superseded",
    name="ck_score_performance_state_known",
    length=32,
)
PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM = _checked_string_enum(
    "pending",
    "running",
    "completed",
    name="ck_performance_recalculation_batches_status_known",
    length=32,
)
PERFORMANCE_RECALCULATION_REASON_ENUM = _checked_string_enum(
    "uncalculated",
    "stale",
    "calculator_version_mismatch",
    "formula_profile_mismatch",
    "unavailable",
    name="ck_performance_recalculation_work_items_reason_known",
    length=64,
)
PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM = _checked_string_enum(
    "pending",
    "claimed",
    "completed",
    "unavailable",
    name="ck_performance_recalculation_work_items_state_known",
    length=32,
)
PLAY_TIME_SOURCE_ENUM = _checked_string_enum(
    "fail_time",
    "beatmap_total_length",
    name="ck_scores_play_time_source_known",
    length=32,
)
SCORE_GRADE_ENUM = _checked_string_enum(
    "XH",
    "X",
    "SH",
    "S",
    "A",
    "B",
    "C",
    "D",
    name="ck_scores_grade_known",
    length=2,
)
SCORE_SUBMISSION_STATE_ENUM = _checked_string_enum(
    "received",
    "processing",
    "completed",
    "terminal_rejected",
    "retryable",
    name="ck_score_submissions_state_known",
    length=32,
)


def upgrade() -> None:
    """閉集合カラムと leaderboard storage を新しい契約へ移行する.

    Returns:
        None: migration が完了したことを示す.

    Raises:
        RuntimeError: Enum の許容値外データまたは重複 score_id を検出した場合.
    """
    _upgrade_score_enums()
    _upgrade_beatmap_enums()
    _upgrade_blob_enums()
    _upgrade_channel_enums()
    _upgrade_personal_best_enums()
    _upgrade_performance_enums()
    _upgrade_leaderboard_storage()


def downgrade() -> None:
    """Enum と leaderboard storage を直前の契約へ戻す.

    Returns:
        None: downgrade が完了したことを示す.

    Notes:
        旧 Global/Selected Mods projection は current checksum の source scores から再生成する.
    """
    _downgrade_performance_enums()
    _downgrade_personal_best_enums()
    _downgrade_channel_enums()
    _downgrade_blob_enums()
    _downgrade_beatmap_enums()
    _downgrade_score_enums()
    _downgrade_leaderboard_storage()


def _upgrade_leaderboard_storage() -> None:
    """Global transitional projectionをstaging table経由で置き換える.

    Returns:
        None: backfill済みGlobal tableへのatomic swapが完了したことを示す.

    Notes:
        live projection tableをDELETEせず, source Score scanとindex構築をstaging側で行う.
    """
    lock_projection_updates()
    _create_global_projection_table(_GLOBAL_PROJECTION_STAGING_TABLE)
    _rebuild_current_global_projection(_GLOBAL_PROJECTION_STAGING_TABLE)
    _validate_unique_projection_score_ids(_GLOBAL_PROJECTION_STAGING_TABLE)
    op.create_unique_constraint(
        _GLOBAL_SCOPE_UNIQUE_CONSTRAINT,
        _GLOBAL_PROJECTION_STAGING_TABLE,
        ["beatmap_id", "ruleset", "playstyle", "user_id"],
    )
    op.create_unique_constraint(
        _GLOBAL_SCORE_UNIQUE_CONSTRAINT,
        _GLOBAL_PROJECTION_STAGING_TABLE,
        ["score_id"],
    )
    op.create_index(
        _GLOBAL_USER_REBUILD_INDEX,
        _GLOBAL_PROJECTION_STAGING_TABLE,
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
    )
    _replace_projection_table(_GLOBAL_PROJECTION_STAGING_TABLE)


def _create_global_projection_table(table_name: str) -> None:
    """Global transitional projection用の空staging tableを作成する.

    Args:
        table_name (str): live tableと競合しないstaging table名.

    Returns:
        None: constraint追加前の空projection tableを作成したことを示す.
    """
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("beatmap_checksum", sa.String(length=32), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("score_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name=_GLOBAL_SCORE_FOREIGN_KEY,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _replace_projection_table(staging_table: str) -> None:
    """完成済みstaging tableをlive projection tableへ置き換える.

    Args:
        staging_table (str): backfillとconstraint/index作成が完了したtable名.

    Returns:
        None: 旧tableをdropしてstaging tableをcanonical名へrenameしたことを示す.

    Notes:
        ACCESS EXCLUSIVE lockが必要な処理を最後のdrop/renameだけに限定する.
    """
    op.drop_table(_PROJECTION_TABLE)
    op.rename_table(staging_table, _PROJECTION_TABLE)


def lock_projection_updates() -> None:
    """migration rebuildをruntime submitとtransaction内で直列化する.

    Returns:
        None: transaction終了までexclusive maintenance lockを保持したことを示す.

    Raises:
        SQLAlchemyError: PostgreSQL advisory lockを取得できない場合.

    Notes:
        Runtime repositoryとnamespaceおよびBlake2b変換契約を共有する.
    """
    statement = sa.select(sa.func.pg_advisory_xact_lock(_projection_rebuild_lock_key()))
    _ = op.get_bind().execute(statement)


def _projection_rebuild_lock_key() -> int:
    """projection maintenance用のsigned 64-bit advisory lock keyを返す.

    Returns:
        int: runtime submit/rebuildと共有するPostgreSQL advisory lock key.
    """
    return int.from_bytes(
        blake2b(_PROJECTION_REBUILD_LOCK_NAMESPACE.encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )


def _rebuild_current_global_projection(projection_table: str) -> None:
    """Current checksumのsource ScoresからGlobal projectionを再構築する.

    Args:
        projection_table (str): source Scoreから再構築するstaging table名.

    Returns:
        None: Natural identityごとのGlobal winnerをstaging projectionへ保存したことを示す.

    Notes:
        Selected Mods行とstale-checksum Global行はsource Scoreから再生成しない.
    """
    projection = sa.table(
        projection_table,
        sa.column("beatmap_id", sa.Integer()),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
        sa.column("beatmap_checksum", sa.String(length=32)),
    )
    scores = sa.table(
        "scores",
        sa.column("id", sa.BigInteger()),
        sa.column("beatmap_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
        sa.column("passed", sa.Boolean()),
        sa.column("leaderboard_eligible_at_submission", sa.Boolean()),
    )
    beatmaps = sa.table(
        "beatmaps",
        sa.column("id", sa.Integer()),
        sa.column("checksum_md5", sa.String(length=32)),
    )
    current_scores = scores.join(
        beatmaps,
        sa.and_(
            beatmaps.c.id == scores.c.beatmap_id,
            beatmaps.c.checksum_md5 == scores.c.beatmap_checksum,
        ),
    )
    ranked = (
        sa.select(
            scores.c.beatmap_id,
            scores.c.ruleset,
            scores.c.playstyle,
            scores.c.user_id,
            scores.c.id.label("score_id"),
            scores.c.score,
            scores.c.submitted_at,
            scores.c.beatmap_checksum,
            sa.func.row_number()
            .over(
                partition_by=(
                    scores.c.beatmap_id,
                    scores.c.ruleset,
                    scores.c.playstyle,
                    scores.c.user_id,
                ),
                order_by=(
                    scores.c.score.desc(),
                    scores.c.submitted_at.asc(),
                    scores.c.id.asc(),
                ),
            )
            .label("candidate_rank"),
        )
        .select_from(current_scores)
        .where(
            scores.c.passed.is_(True),
            scores.c.leaderboard_eligible_at_submission.is_(True),
        )
        .subquery("ranked_current_global_projection")
    )

    op.execute(
        sa.insert(projection).from_select(
            (
                "beatmap_id",
                "ruleset",
                "playstyle",
                "user_id",
                "score_id",
                "score",
                "submitted_at",
                "beatmap_checksum",
            ),
            sa.select(
                ranked.c.beatmap_id,
                ranked.c.ruleset,
                ranked.c.playstyle,
                ranked.c.user_id,
                ranked.c.score_id,
                ranked.c.score,
                ranked.c.submitted_at,
                ranked.c.beatmap_checksum,
            ).where(ranked.c.candidate_rank == 1),
        )
    )


def _downgrade_leaderboard_storage() -> None:
    """pre-0400 projectionをstaging table経由で復元する.

    Returns:
        None: Global/Selected Mods legacy tableへのatomic swapが完了したことを示す.
    """
    lock_projection_updates()
    _create_legacy_projection_table(_LEGACY_PROJECTION_STAGING_TABLE)
    _restore_legacy_leaderboard_projection(_LEGACY_PROJECTION_STAGING_TABLE)
    mod_filter_key = sa.column("mod_filter_key", sa.Integer())
    op.create_index(
        _LEGACY_SCOPE_UNIQUE_INDEX,
        _LEGACY_PROJECTION_STAGING_TABLE,
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            sa.func.coalesce(mod_filter_key, -1),
        ],
        unique=True,
    )
    op.create_index(
        _LEGACY_ORDERING_INDEX,
        _LEGACY_PROJECTION_STAGING_TABLE,
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            sa.func.coalesce(mod_filter_key, -1),
            sa.column("score", sa.Integer()).desc(),
            sa.column("submitted_at", sa.DateTime(timezone=True)).asc(),
            sa.column("score_id", sa.BigInteger()).asc(),
        ],
    )
    op.create_index(
        _LEGACY_USER_REBUILD_INDEX,
        _LEGACY_PROJECTION_STAGING_TABLE,
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
    )
    _replace_projection_table(_LEGACY_PROJECTION_STAGING_TABLE)


def _create_legacy_projection_table(table_name: str) -> None:
    """pre-0400 projection用の空staging tableを作成する.

    Args:
        table_name (str): live tableと競合しないstaging table名.

    Returns:
        None: legacy column/constraintを持つ空tableを作成したことを示す.
    """
    mod_filter_key = sa.column("mod_filter_key", sa.Integer())
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mod_filter_key", sa.Integer(), nullable=True),
        sa.Column("score_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            sa.or_(mod_filter_key.is_(None), mod_filter_key >= 0),
            name=_LEGACY_MODS_CHECK_CONSTRAINT,
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name=_LEGACY_SCORE_FOREIGN_KEY,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _restore_legacy_leaderboard_projection(projection_table: str) -> None:
    """0400 downgradeで旧mod_filter_key projectionを再構築する.

    Args:
        projection_table (str): legacy rowsを書き込むstaging table名.

    Returns:
        None: 旧schema向けのGlobalとSelected Mods代表行を保存したことを示す.

    Notes:
        pre-0400のhistorical filter key互換としてNC->DT, PF->SD, Mirror除外を
        この関数内だけで適用する. 0600以降の現行schemaはScoreのraw Mod bitmaskを
        projection identityとして使用する.
    """
    projection = sa.table(
        projection_table,
        sa.column("beatmap_id", sa.Integer()),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mod_filter_key", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
    )
    scores = sa.table(
        "scores",
        sa.column("id", sa.BigInteger()),
        sa.column("beatmap_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mods", sa.Integer()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
        sa.column("passed", sa.Boolean()),
        sa.column("leaderboard_eligible_at_submission", sa.Boolean()),
    )
    beatmaps = sa.table(
        "beatmaps",
        sa.column("id", sa.Integer()),
        sa.column("checksum_md5", sa.String(length=32)),
    )
    current_scores = scores.join(
        beatmaps,
        sa.and_(
            beatmaps.c.id == scores.c.beatmap_id,
            beatmaps.c.checksum_md5 == scores.c.beatmap_checksum,
        ),
    )
    common_columns = (
        scores.c.beatmap_id,
        scores.c.ruleset,
        scores.c.playstyle,
        scores.c.user_id,
    )
    common_filter = sa.and_(
        scores.c.passed.is_(True),
        scores.c.leaderboard_eligible_at_submission.is_(True),
    )
    global_candidates = (
        sa.select(
            *common_columns,
            sa.cast(sa.null(), sa.Integer()).label("mod_filter_key"),
            scores.c.id.label("score_id"),
            scores.c.score,
            scores.c.submitted_at,
        )
        .select_from(current_scores)
        .where(common_filter)
    )
    legacy_filter_mods_without_nightcore = sa.case(
        (
            scores.c.mods.bitwise_and(_LEGACY_NIGHTCORE_BIT) != 0,
            scores.c.mods.bitwise_or(_LEGACY_DOUBLE_TIME_BIT).bitwise_and(~_LEGACY_NIGHTCORE_BIT),
        ),
        else_=scores.c.mods,
    )
    legacy_filter_mods_without_perfect = sa.case(
        (
            legacy_filter_mods_without_nightcore.bitwise_and(_LEGACY_PERFECT_BIT) != 0,
            legacy_filter_mods_without_nightcore.bitwise_or(_LEGACY_SUDDEN_DEATH_BIT).bitwise_and(
                ~_LEGACY_PERFECT_BIT
            ),
        ),
        else_=legacy_filter_mods_without_nightcore,
    )
    legacy_filter_mods = legacy_filter_mods_without_perfect.bitwise_and(~_LEGACY_MIRROR_BIT)
    is_legacy_no_mod_candidate = (
        legacy_filter_mods.bitwise_and(~_LEGACY_PREFERENCE_ONLY_NO_MODS_BITS) == 0
    )
    legacy_mod_filter_keys = sa.case(
        (
            sa.and_(is_legacy_no_mod_candidate, legacy_filter_mods == 0),
            postgresql.array([0]),
        ),
        (
            is_legacy_no_mod_candidate,
            postgresql.array([0, legacy_filter_mods]),
        ),
        else_=postgresql.array([legacy_filter_mods]),
    )
    mod_filter_key = sa.func.unnest(legacy_mod_filter_keys).column_valued(
        "mod_filter_key", joins_implicitly=True
    )
    selected_mod_candidates = (
        sa.select(
            *common_columns,
            mod_filter_key,
            scores.c.id.label("score_id"),
            scores.c.score,
            scores.c.submitted_at,
        )
        .select_from(current_scores)
        .where(common_filter)
    )
    candidates = sa.union_all(global_candidates, selected_mod_candidates).subquery(
        "legacy_leaderboard_candidates"
    )
    ranked = sa.select(
        *tuple(candidates.c),
        sa.func.row_number()
        .over(
            partition_by=(
                candidates.c.beatmap_id,
                candidates.c.ruleset,
                candidates.c.playstyle,
                candidates.c.user_id,
                candidates.c.mod_filter_key,
            ),
            order_by=(
                candidates.c.score.desc(),
                candidates.c.submitted_at.asc(),
                candidates.c.score_id.asc(),
            ),
        )
        .label("candidate_rank"),
    ).subquery("ranked_legacy_leaderboard_candidates")

    op.execute(
        sa.insert(projection).from_select(
            (
                "beatmap_id",
                "ruleset",
                "playstyle",
                "user_id",
                "mod_filter_key",
                "score_id",
                "score",
                "submitted_at",
            ),
            sa.select(
                ranked.c.beatmap_id,
                ranked.c.ruleset,
                ranked.c.playstyle,
                ranked.c.user_id,
                ranked.c.mod_filter_key,
                ranked.c.score_id,
                ranked.c.score,
                ranked.c.submitted_at,
            ).where(ranked.c.candidate_rank == 1),
        )
    )


def _upgrade_score_enums() -> None:
    _create_enum_constraint("scores", "grade", SCORE_GRADE_ENUM)
    _create_enum_constraint(
        "scores",
        "beatmap_status_at_submission",
        BEATMAP_RANK_STATUS_ENUM,
    )
    _validate_enum_column("scores", "play_time_source", PLAY_TIME_SOURCE_ENUM)
    _create_enum_constraint(
        "score_submissions",
        "state",
        SCORE_SUBMISSION_STATE_ENUM,
    )


def _downgrade_score_enums() -> None:
    _drop_enum_constraint(
        "score_submissions",
        SCORE_SUBMISSION_STATE_ENUM,
    )
    _drop_enum_constraint(
        "scores",
        BEATMAP_RANK_STATUS_ENUM,
    )
    _drop_enum_constraint("scores", SCORE_GRADE_ENUM)


def _upgrade_beatmap_enums() -> None:
    beatmaps = sa.table("beatmaps", sa.column("mode", sa.String(length=16)))
    fetch_states = sa.table(
        "beatmap_fetch_states",
        sa.column("target_type", sa.String(length=32)),
    )
    op.execute(
        sa.update(beatmaps)
        .where(beatmaps.c.mode.not_in(("osu", "taiko", "fruits", "mania")))
        .values(mode="unknown")
    )
    op.execute(
        sa.update(fetch_states).values(
            target_type=sa.case(
                (fetch_states.c.target_type == "beatmap", "metadata:beatmap"),
                (fetch_states.c.target_type == "beatmapset", "metadata:beatmapset"),
                (fetch_states.c.target_type == "checksum", "metadata:checksum"),
                (fetch_states.c.target_type == "file", "file:beatmap"),
                else_=fetch_states.c.target_type,
            )
        )
    )
    _create_enum_constraint(
        "beatmapsets",
        "official_status",
        BEATMAP_RANK_STATUS_ENUM,
    )
    _create_enum_constraint(
        "beatmapsets",
        "official_status_source",
        BEATMAP_METADATA_SOURCE_ENUM,
    )
    _create_enum_constraint(
        "beatmaps",
        "mode",
        BEATMAP_MODE_ENUM,
    )
    _create_enum_constraint(
        "beatmaps",
        "official_status",
        BEATMAP_RANK_STATUS_ENUM,
    )
    _create_enum_constraint(
        "beatmaps",
        "official_status_source",
        BEATMAP_METADATA_SOURCE_ENUM,
    )
    _create_enum_constraint(
        "beatmaps",
        "local_status_override",
        LOCAL_BEATMAP_STATUS_ENUM,
    )
    _create_enum_constraint(
        "beatmap_file_attachments",
        "source",
        BEATMAP_FILE_SOURCE_ENUM,
    )
    _create_enum_constraint(
        "beatmap_fetch_states",
        "target_type",
        BEATMAP_FETCH_TARGET_KIND_ENUM,
    )
    _create_enum_constraint(
        "beatmap_fetch_states",
        "status",
        BEATMAP_FETCH_STATE_ENUM,
    )


def _downgrade_beatmap_enums() -> None:
    _drop_enum_constraint(
        "beatmap_fetch_states",
        BEATMAP_FETCH_STATE_ENUM,
    )
    _drop_enum_constraint(
        "beatmap_fetch_states",
        BEATMAP_FETCH_TARGET_KIND_ENUM,
    )
    fetch_states = sa.table(
        "beatmap_fetch_states",
        sa.column("target_type", sa.String(length=32)),
    )
    op.execute(
        sa.update(fetch_states).values(
            target_type=sa.case(
                (fetch_states.c.target_type == "metadata:beatmap", "beatmap"),
                (fetch_states.c.target_type == "metadata:beatmapset", "beatmapset"),
                (fetch_states.c.target_type == "metadata:checksum", "checksum"),
                (fetch_states.c.target_type == "file:beatmap", "file"),
                else_=fetch_states.c.target_type,
            )
        )
    )
    _drop_enum_constraint(
        "beatmap_file_attachments",
        BEATMAP_FILE_SOURCE_ENUM,
    )
    _drop_enum_constraint(
        "beatmaps",
        LOCAL_BEATMAP_STATUS_ENUM,
    )
    _drop_enum_constraint(
        "beatmaps",
        BEATMAP_MODE_ENUM,
    )
    _drop_enum_constraint(
        "beatmaps",
        BEATMAP_METADATA_SOURCE_ENUM,
    )
    _drop_enum_constraint(
        "beatmaps",
        BEATMAP_RANK_STATUS_ENUM,
    )
    _drop_enum_constraint(
        "beatmapsets",
        BEATMAP_METADATA_SOURCE_ENUM,
    )
    _drop_enum_constraint(
        "beatmapsets",
        BEATMAP_RANK_STATUS_ENUM,
    )


def _upgrade_blob_enums() -> None:
    _create_enum_constraint(
        "blobs",
        "storage_backend",
        BLOB_STORAGE_BACKEND_ENUM,
    )


def _downgrade_blob_enums() -> None:
    _drop_enum_constraint(
        "blobs",
        BLOB_STORAGE_BACKEND_ENUM,
    )


def _upgrade_channel_enums() -> None:
    _create_enum_constraint(
        "channels",
        "channel_type",
        CHANNEL_TYPE_ENUM,
    )


def _downgrade_channel_enums() -> None:
    _drop_enum_constraint(
        "channels",
        CHANNEL_TYPE_ENUM,
    )


def _upgrade_personal_best_enums() -> None:
    _create_enum_constraint(
        "personal_bests",
        "category",
        LEADERBOARD_CATEGORY_ENUM,
    )


def _downgrade_personal_best_enums() -> None:
    _drop_enum_constraint(
        "personal_bests",
        LEADERBOARD_CATEGORY_ENUM,
    )


def _upgrade_performance_enums() -> None:
    state = sa.column("state", sa.String(length=32))
    claim_owner = sa.column("claim_owner", sa.String(length=128))
    claim_expires_at = sa.column("claim_expires_at", sa.DateTime(timezone=True))
    calculations = sa.table(
        "score_performance_calculations",
        state,
        claim_owner,
        claim_expires_at,
    )
    work_item_state = sa.column("state", sa.String(length=32))
    work_item_claim_owner = sa.column("claim_owner", sa.String(length=128))
    work_item_claim_expires_at = sa.column(
        "claim_expires_at",
        sa.DateTime(timezone=True),
    )

    _validate_enum_column(
        "score_performance_calculations",
        "state",
        PERFORMANCE_CALCULATION_STATE_ENUM,
    )
    _create_enum_constraint(
        "score_performance_calculations",
        "formula_profile",
        FORMULA_PROFILE_ENUM,
    )
    op.execute(
        sa.update(calculations)
        .where(state.not_in(("queued", "fetching_file", "calculating")))
        .values(claim_owner=None, claim_expires_at=None)
    )
    op.create_check_constraint(
        "ck_score_performance_claim_metadata_pair",
        "score_performance_calculations",
        sa.or_(
            sa.and_(
                state.in_(("queued", "fetching_file", "calculating")),
                sa.or_(
                    sa.and_(claim_owner.is_(None), claim_expires_at.is_(None)),
                    sa.and_(claim_owner.is_not(None), claim_expires_at.is_not(None)),
                ),
            ),
            sa.and_(
                state.not_in(("queued", "fetching_file", "calculating")),
                claim_owner.is_(None),
                claim_expires_at.is_(None),
            ),
        ),
    )
    _create_enum_constraint(
        "performance_recalculation_batches",
        "status",
        PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM,
    )
    _create_enum_constraint(
        "performance_recalculation_batches",
        "target_formula_profile",
        FORMULA_PROFILE_ENUM,
    )
    _create_enum_constraint(
        "performance_recalculation_work_items",
        "reason",
        PERFORMANCE_RECALCULATION_REASON_ENUM,
    )
    _create_enum_constraint(
        "performance_recalculation_work_items",
        "state",
        PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM,
    )
    op.create_check_constraint(
        "ck_performance_recalculation_work_item_claim_metadata",
        "performance_recalculation_work_items",
        sa.or_(
            sa.and_(
                work_item_state == "claimed",
                work_item_claim_owner.is_not(None),
                work_item_claim_expires_at.is_not(None),
            ),
            sa.and_(
                work_item_state != "claimed",
                work_item_claim_owner.is_(None),
                work_item_claim_expires_at.is_(None),
            ),
        ),
    )


def _downgrade_performance_enums() -> None:
    op.drop_constraint(
        "ck_performance_recalculation_work_item_claim_metadata",
        "performance_recalculation_work_items",
        type_="check",
        if_exists=True,
    )
    _drop_enum_constraint(
        "performance_recalculation_work_items",
        PERFORMANCE_RECALCULATION_WORK_ITEM_STATE_ENUM,
    )
    _drop_enum_constraint(
        "performance_recalculation_work_items",
        PERFORMANCE_RECALCULATION_REASON_ENUM,
    )
    _drop_enum_constraint(
        "performance_recalculation_batches",
        FORMULA_PROFILE_ENUM,
    )
    _drop_enum_constraint(
        "performance_recalculation_batches",
        PERFORMANCE_RECALCULATION_BATCH_STATUS_ENUM,
    )
    op.drop_constraint(
        "ck_score_performance_claim_metadata_pair",
        "score_performance_calculations",
        type_="check",
        if_exists=True,
    )
    _drop_enum_constraint(
        "score_performance_calculations",
        FORMULA_PROFILE_ENUM,
    )


def _create_enum_constraint(
    table_name: str,
    column_name: str,
    enum_type: sa.Enum,
) -> None:
    column = sa.column(
        column_name,
        sa.String(length=enum_type.length),
    )
    # Enforce concurrent writes before scanning legacy rows without a long exclusive lock.
    op.create_check_constraint(
        _enum_constraint_name(enum_type),
        table_name,
        column.in_(tuple(enum_type.enums)),
        postgresql_not_valid=True,
    )
    _validate_enum_column(table_name, column_name, enum_type)


def _drop_enum_constraint(table_name: str, enum_type: sa.Enum) -> None:
    op.drop_constraint(
        _enum_constraint_name(enum_type),
        table_name,
        type_="check",
    )


def _enum_constraint_name(enum_type: sa.Enum) -> str:
    constraint_name = enum_type.name
    if constraint_name is None:
        msg = "checked string Enum requires an explicit constraint name"
        raise RuntimeError(msg)
    return constraint_name


def _validate_enum_column(
    table_name: str,
    column_name: str,
    enum_type: sa.Enum,
) -> None:
    column = sa.column(column_name, sa.String())
    table = sa.table(table_name, column)
    statement = (
        sa.select(column)
        .select_from(table)
        .where(
            column.is_not(None),
            column.not_in(tuple(enum_type.enums)),
        )
        .distinct()
        .limit(10)
    )
    invalid_rows = cast(
        "Sequence[tuple[object]]",
        op.get_bind().execute(statement).all(),
    )
    invalid_values = tuple(str(row[0]) for row in invalid_rows)
    if invalid_values:
        msg = (
            f"{table_name}.{column_name} contains values outside {enum_type.name}: "
            f"{invalid_values!r}"
        )
        raise RuntimeError(msg)


def _validate_unique_projection_score_ids(projection_table: str) -> None:
    """staging projection内のscore_id重複を検出する.

    Args:
        projection_table (str): unique constraint追加前のstaging table名.

    Returns:
        None: score_idが全行で一意であることを示す.

    Raises:
        RuntimeError: 重複score_idを最大10件検出した場合.
    """
    projection = sa.table(
        projection_table,
        sa.column("score_id", sa.BigInteger()),
    )
    statement = (
        sa.select(projection.c.score_id)
        .group_by(projection.c.score_id)
        .having(sa.func.count() > 1)
        .order_by(projection.c.score_id)
        .limit(10)
    )
    duplicate_score_ids = tuple(
        cast(
            "Sequence[int]",
            op.get_bind().execute(statement).scalars().all(),
        )
    )
    if duplicate_score_ids:
        msg = (
            f"{projection_table} contains duplicate all-mods score_id values: "
            f"{duplicate_score_ids!r}"
        )
        raise RuntimeError(msg)
