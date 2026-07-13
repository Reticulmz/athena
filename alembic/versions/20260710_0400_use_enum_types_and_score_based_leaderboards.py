"""CHECK付き文字列Enumとscore正本のleaderboard filterを導入するmigration.

Revision ID: 20260710_0400
Revises: 20260710_0300
Create Date: 2026-07-10 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.sql.elements import ColumnElement

revision: str = "20260710_0400"
down_revision: str | None = "20260710_0300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NIGHTCORE_BIT = 1 << 9
_DOUBLE_TIME_BIT = 1 << 6
_PERFECT_BIT = 1 << 14
_SUDDEN_DEATH_BIT = 1 << 5
_MIRROR_BIT = 1 << 30
_PREFERENCE_ONLY_NO_MODS_BITS = _SUDDEN_DEATH_BIT | _PERFECT_BIT | _MIRROR_BIT


def _selected_mod_filter_keys_expression(
    mods: ColumnElement[int],
) -> ColumnElement[list[int]]:
    nightcore_normalized = sa.case(
        (
            mods.bitwise_and(_NIGHTCORE_BIT) != 0,
            mods.bitwise_or(_DOUBLE_TIME_BIT).bitwise_and(~_NIGHTCORE_BIT),
        ),
        else_=mods,
    )
    perfect_normalized = sa.case(
        (
            nightcore_normalized.bitwise_and(_PERFECT_BIT) != 0,
            nightcore_normalized.bitwise_or(_SUDDEN_DEATH_BIT).bitwise_and(~_PERFECT_BIT),
        ),
        else_=nightcore_normalized,
    )
    canonical_mods = perfect_normalized.bitwise_and(~_MIRROR_BIT)
    is_no_mod_candidate = canonical_mods.bitwise_and(~_PREFERENCE_ONLY_NO_MODS_BITS) == 0
    return sa.case(
        (
            sa.and_(is_no_mod_candidate, canonical_mods == 0),
            postgresql.array([0]),
        ),
        (
            is_no_mod_candidate,
            postgresql.array([0, canonical_mods]),
        ),
        else_=postgresql.array([canonical_mods]),
    )


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
    _upgrade_leaderboard_storage()
    _upgrade_score_enums()
    _upgrade_beatmap_enums()
    _upgrade_blob_enums()
    _upgrade_channel_enums()
    _upgrade_personal_best_enums()
    _upgrade_performance_enums()


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
    op.add_column(
        "beatmap_leaderboard_user_bests",
        sa.Column("beatmap_checksum", sa.String(length=32), nullable=True),
    )
    _rebuild_current_global_projection()
    op.alter_column(
        "beatmap_leaderboard_user_bests",
        "beatmap_checksum",
        existing_type=sa.String(length=32),
        existing_nullable=True,
        nullable=False,
    )
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_ordering",
        table_name="beatmap_leaderboard_user_bests",
    )
    _validate_unique_projection_score_ids()
    op.drop_constraint(
        "ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative",
        "beatmap_leaderboard_user_bests",
        type_="check",
    )
    op.drop_column("beatmap_leaderboard_user_bests", "mod_filter_key")
    op.create_unique_constraint(
        "uq_beatmap_leaderboard_user_bests_scope",
        "beatmap_leaderboard_user_bests",
        ["beatmap_id", "ruleset", "playstyle", "user_id"],
    )
    op.create_unique_constraint(
        "uq_beatmap_leaderboard_user_bests_score_id",
        "beatmap_leaderboard_user_bests",
        ["score_id"],
    )


def _rebuild_current_global_projection() -> None:
    """Current checksumのsource ScoresからGlobal projectionを再構築する.

    Returns:
        None: Natural identityごとのGlobal winnerを旧projectionへ保存したことを示す.

    Notes:
        Migration upgrade中に全旧projection行を置き換え、Selected Mods行と
        stale-checksum Global行を同時に除去する.
    """
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
        sa.column("beatmap_id", sa.Integer()),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mod_filter_key", sa.Integer()),
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
            sa.cast(sa.null(), sa.Integer()).label("mod_filter_key"),
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

    op.execute(sa.delete(projection))
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
                "beatmap_checksum",
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
                ranked.c.beatmap_checksum,
            ).where(ranked.c.candidate_rank == 1),
        )
    )


def _downgrade_leaderboard_storage() -> None:
    mod_filter_key = sa.column("mod_filter_key", sa.Integer())
    op.drop_constraint(
        "uq_beatmap_leaderboard_user_bests_score_id",
        "beatmap_leaderboard_user_bests",
        type_="unique",
    )
    op.drop_constraint(
        "uq_beatmap_leaderboard_user_bests_scope",
        "beatmap_leaderboard_user_bests",
        type_="unique",
    )
    op.add_column(
        "beatmap_leaderboard_user_bests",
        sa.Column(
            "mod_filter_key",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.drop_column("beatmap_leaderboard_user_bests", "beatmap_checksum")
    _restore_legacy_leaderboard_projection()
    op.create_check_constraint(
        "ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative",
        "beatmap_leaderboard_user_bests",
        sa.or_(mod_filter_key.is_(None), mod_filter_key >= 0),
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        "beatmap_leaderboard_user_bests",
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
        "idx_beatmap_leaderboard_user_bests_ordering",
        "beatmap_leaderboard_user_bests",
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


def _restore_legacy_leaderboard_projection() -> None:
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
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
    mod_filter_key = sa.func.unnest(
        _selected_mod_filter_keys_expression(scores.c.mods)
    ).column_valued("mod_filter_key", joins_implicitly=True)
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

    op.execute(sa.delete(projection))
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
    _validate_enum_column(table_name, column_name, enum_type)
    column = sa.column(
        column_name,
        sa.String(length=enum_type.length),
    )
    op.create_check_constraint(
        _enum_constraint_name(enum_type),
        table_name,
        column.in_(tuple(enum_type.enums)),
    )


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


def _validate_unique_projection_score_ids() -> None:
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
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
            "beatmap_leaderboard_user_bests contains duplicate all-mods score_id values: "
            f"{duplicate_score_ids!r}"
        )
        raise RuntimeError(msg)
