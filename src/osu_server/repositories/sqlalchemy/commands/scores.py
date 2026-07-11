"""SQLAlchemy command-side score repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import Select, case, func, literal, select, update
from sqlalchemy.exc import IntegrityError

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts
from osu_server.repositories.sqlalchemy.models.beatmap import BeatmapModel
from osu_server.repositories.sqlalchemy.models.score import ScoreModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

_EXCLUDED_INITIAL_STATS_MODS = int(Mod.RELAX | Mod.AUTOPILOT)


class SQLAlchemyScoreCommandRepository:
    """Score command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def create(self, score: Score) -> Score:
        model = ScoreModel(
            user_id=score.user_id,
            beatmap_id=score.beatmap_id,
            beatmap_checksum=score.beatmap_checksum,
            online_checksum=score.online_checksum,
            ruleset=score.ruleset.value,
            playstyle=score.playstyle.value,
            mods=score.mods.to_persistence_bitmask(),
            n300=score.n300,
            n100=score.n100,
            n50=score.n50,
            geki=score.geki,
            katu=score.katu,
            miss=score.miss,
            score=score.score,
            max_combo=score.max_combo,
            accuracy=score.accuracy,
            grade=score.grade.value,
            passed=score.passed,
            perfect=score.perfect,
            client_version=score.client_version,
            submitted_at=score.submitted_at,
            beatmap_status_at_submission=(
                score.beatmap_status_at_submission.value
                if score.beatmap_status_at_submission is not None
                else None
            ),
            leaderboard_eligible_at_submission=score.leaderboard_eligible_at_submission,
            fail_time_ms=score.fail_time_ms,
            play_time_seconds=score.play_time_seconds,
            play_time_source=score.play_time_source.value if score.play_time_source else None,
            submit_exit_classification=score.submit_exit_classification,
            replay_view_count=score.replay_view_count,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "online_checksum" in str(exc):
                msg = f"online_checksum already exists: {score.online_checksum}"
                raise ValueError(msg) from exc
            raise
        await self._session.refresh(model)
        return _score_to_domain(model)

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        result = (
            await self._session.execute(
                select(ScoreModel.id).where(ScoreModel.online_checksum == checksum)
            )
        ).scalar_one_or_none()
        return result is not None

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        model = (
            await self._session.execute(
                select(ScoreModel).where(ScoreModel.online_checksum == checksum)
            )
        ).scalar_one_or_none()
        return _score_to_domain(model) if isinstance(model, ScoreModel) else None

    async def get_by_id(self, score_id: int) -> Score | None:
        model = await self._session.get(ScoreModel, score_id)
        return _score_to_domain(model) if isinstance(model, ScoreModel) else None

    async def increment_replay_view_count(self, score_id: int) -> bool:
        """対象 score の Replay View Count を 1 増やす。

        引数:
            score_id: 更新対象 score の identifier.

        戻り値:
            対象 score が存在し、更新された場合は True.

        例外:
            SQLAlchemy session の永続化例外は呼び出し元へ送出する.

        制約:
            Unit of Work 所有 session を使い、この method では commit しない.
        """
        stmt = (
            update(ScoreModel)
            .where(ScoreModel.id == score_id)
            .values(replay_view_count=ScoreModel.replay_view_count + 1)
            .returning(ScoreModel.id)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one_or_none() is not None

    async def count_submissions_for_beatmap(self, beatmap_id: int) -> BeatmapSubmissionCounts:
        raw_row = cast(
            "object",
            (await self._session.execute(_beatmap_submission_counts_statement(beatmap_id))).one(),
        )
        row = cast(
            "tuple[object, object]",
            raw_row,
        )
        play_count, pass_count = row
        return BeatmapSubmissionCounts(
            play_count=_count_value(play_count),
            pass_count=_count_value(pass_count),
        )

    async def list_current_stats_scores_for_user(
        self,
        user_id: int,
        *,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[Score, ...]:
        models = (
            await self._session.execute(
                _current_stats_scores_statement(
                    user_id,
                    ruleset=ruleset,
                    playstyle=playstyle,
                )
            )
        ).scalars()
        return tuple(_score_to_domain(model) for model in models)

    async def list_leaderboard_rebuild_candidates_for_user(
        self,
        user_id: int,
    ) -> tuple[Score, ...]:
        models = (
            await self._session.execute(
                _leaderboard_rebuild_candidate_statement().where(ScoreModel.user_id == user_id)
            )
        ).scalars()
        return tuple(_score_to_domain(model) for model in models)

    async def list_leaderboard_rebuild_candidates_for_beatmap_ids(
        self,
        beatmap_ids: tuple[int, ...],
    ) -> tuple[Score, ...]:
        if len(beatmap_ids) == 0:
            return ()
        models = (
            await self._session.execute(
                _leaderboard_rebuild_candidate_statement().where(
                    ScoreModel.beatmap_id.in_(beatmap_ids)
                )
            )
        ).scalars()
        return tuple(_score_to_domain(model) for model in models)


def _score_to_domain(model: ScoreModel) -> Score:
    return Score(
        id=model.id,
        user_id=model.user_id,
        beatmap_id=model.beatmap_id,
        beatmap_checksum=model.beatmap_checksum,
        online_checksum=model.online_checksum,
        ruleset=Ruleset(model.ruleset),
        playstyle=Playstyle(model.playstyle),
        mods=ModCombination.from_persistence_bitmask(model.mods),
        n300=model.n300,
        n100=model.n100,
        n50=model.n50,
        geki=model.geki,
        katu=model.katu,
        miss=model.miss,
        score=model.score,
        max_combo=model.max_combo,
        accuracy=model.accuracy,
        grade=Grade(model.grade),
        passed=model.passed,
        perfect=model.perfect,
        client_version=model.client_version,
        submitted_at=model.submitted_at,
        beatmap_status_at_submission=(
            BeatmapRankStatus(model.beatmap_status_at_submission)
            if model.beatmap_status_at_submission is not None
            else None
        ),
        leaderboard_eligible_at_submission=model.leaderboard_eligible_at_submission,
        fail_time_ms=model.fail_time_ms,
        play_time_seconds=model.play_time_seconds,
        play_time_source=(
            PlayTimeSource(model.play_time_source) if model.play_time_source is not None else None
        ),
        submit_exit_classification=model.submit_exit_classification,
        replay_view_count=model.replay_view_count,
    )


def _beatmap_submission_counts_statement(beatmap_id: int) -> Select[tuple[int, int]]:
    return select(
        func.count(ScoreModel.id),
        func.coalesce(
            func.sum(case((ScoreModel.passed.is_(True), 1), else_=0)),
            0,
        ),
    ).where(ScoreModel.beatmap_id == beatmap_id)


def _count_value(value: object) -> int:
    if isinstance(value, bool):
        msg = "count value must be an integer"
        raise TypeError(msg)
    if isinstance(value, int):
        return value
    msg = f"count value must be an integer: {value!r}"
    raise TypeError(msg)


def _current_stats_scores_statement(
    user_id: int,
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> Select[tuple[ScoreModel]]:
    return (
        select(ScoreModel)
        .where(
            ScoreModel.user_id == user_id,
            ScoreModel.ruleset == ruleset.value,
            ScoreModel.playstyle == playstyle.value,
            _initial_stats_mod_condition(),
        )
        .order_by(ScoreModel.submitted_at.asc(), ScoreModel.id.asc())
    )


def _initial_stats_mod_condition() -> ColumnElement[bool]:
    return ScoreModel.mods.bitwise_and(_EXCLUDED_INITIAL_STATS_MODS) == literal(0)


def _leaderboard_rebuild_candidate_statement() -> Select[tuple[ScoreModel]]:
    return (
        select(ScoreModel)
        .join(BeatmapModel, BeatmapModel.id == ScoreModel.beatmap_id)
        .where(
            ScoreModel.passed.is_(True),
            ScoreModel.leaderboard_eligible_at_submission.is_(True),
            ScoreModel.beatmap_checksum == BeatmapModel.checksum_md5,
        )
        .order_by(
            ScoreModel.beatmap_id.asc(),
            ScoreModel.ruleset.asc(),
            ScoreModel.playstyle.asc(),
            ScoreModel.user_id.asc(),
            ScoreModel.score.desc(),
            ScoreModel.submitted_at.asc(),
            ScoreModel.id.asc(),
        )
    )
