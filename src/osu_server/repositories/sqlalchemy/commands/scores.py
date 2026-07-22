"""SQLAlchemyでscoreとscore由来projection入力を永続化するrepositoryを提供する."""

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
    """Unit of Work所有sessionでscoreを読み書きするrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): score操作に使うsession.

        Returns:
            None: repositoryの初期化完了を示す.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def create(self, score: Score) -> Score:
        """新しいscoreを永続化してdomain modelへ変換する.

        Args:
            score (Score): score値とsubmission metadataを持つ新規score.

        Returns:
            Score: flushとrefresh後の永続化済みscore.

        Raises:
            ValueError: 同じonline_checksumのscoreが既に存在する場合.
            SQLAlchemyError: checksum重複以外の永続化処理に失敗した場合.

        Notes:
            このmethodはUnit of Workをcommitしない.
        """
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
        """Online checksumを持つscoreが存在するか確認する.

        Args:
            checksum (str): 確認対象scoreのonline checksum.

        Returns:
            bool: 対応するscoreが存在する場合はTrue. 存在しない場合はFalse.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        result = (
            await self._session.execute(
                select(ScoreModel.id).where(ScoreModel.online_checksum == checksum)
            )
        ).scalar_one_or_none()
        return result is not None

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Online checksumで保存済みscoreを取得する.

        Args:
            checksum (str): 取得対象scoreのonline checksum.

        Returns:
            Score | None: 対応するscore. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (
            await self._session.execute(
                select(ScoreModel).where(ScoreModel.online_checksum == checksum)
            )
        ).scalar_one_or_none()
        return _score_to_domain(model) if isinstance(model, ScoreModel) else None

    async def get_by_id(self, score_id: int) -> Score | None:
        """永続化識別子で保存済みscoreを取得する.

        Args:
            score_id (int): 取得対象scoreの永続化識別子.

        Returns:
            Score | None: 対応するscore. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = await self._session.get(ScoreModel, score_id)
        return _score_to_domain(model) if isinstance(model, ScoreModel) else None

    async def increment_replay_view_count(self, score_id: int) -> bool:
        """指定scoreのreplay view countを1増加させる.

        Args:
            score_id (int): 更新対象scoreの永続化識別子.

        Returns:
            bool: 対象scoreが存在し更新した場合はTrue. 存在しない場合はFalse.

        Raises:
            SQLAlchemyError: updateまたはflushに失敗した場合.

        Notes:
            Unit of Work所有sessionを使いこのmethodではcommitしない.
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
        """beatmapへのscore submission数とpass数を集計する.

        Args:
            beatmap_id (int): 集計対象beatmapの永続化識別子.

        Returns:
            BeatmapSubmissionCounts: 全submission数とpassed score数を持つ集計値.

        Raises:
            TypeError: database結果のcount値が整数として扱えない場合.
            SQLAlchemyError: 集計selectの実行に失敗した場合.
        """
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
        """UserStats更新に使うuserのscoreを時系列順で取得する.

        Args:
            user_id (int): scoreを取得するuserの永続化識別子.
            ruleset (Ruleset): 取得対象のruleset.
            playstyle (Playstyle): 取得対象のplaystyle.

        Returns:
            tuple[Score, ...]: submission時刻とidの昇順で並ぶ対象score.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.

        Notes:
            RELAXとAUTOPILOT modを含むscoreはinitial statisticsから除外する.
        """
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
        """1 userのleaderboard projection再構築候補scoreを取得する.

        Args:
            user_id (int): 候補を取得するuserの永続化識別子.

        Returns:
            tuple[Score, ...]: leaderboard適格条件を満たすscoreの決定的な順序のtuple.

        Raises:
            SQLAlchemyError: join selectの実行に失敗した場合.
        """
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
        """指定beatmap群のleaderboard projection再構築候補scoreを取得する.

        Args:
            beatmap_ids (tuple[int, ...]): 候補を取得するbeatmapの永続化識別子.

        Returns:
            tuple[Score, ...]: leaderboard適格条件を満たすscoreの決定的な順序のtuple.

        Raises:
            SQLAlchemyError: join selectの実行に失敗した場合.

        Notes:
            空tuple入力ではSQLを実行せず空tupleを返す.
        """
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
    """SQLAlchemy score modelをscore domain modelへ変換する.

    Args:
        model (ScoreModel): 永続化層から読み出したscore row. modsは非負のbitmaskであり
            非nullのplay_time_sourceは既知のPlayTimeSource値でなければならない.

    Returns:
        Score: 有限値と非負のmod bitmaskをdomain表現へ復元したscore.

    Raises:
        ValueError: model.modsが負でModCombinationへ復元できない場合.
            またはrulesetかplaystyleかgradeか非nullのbeatmap_status_at_submissionか
            非nullのplay_time_sourceが既知のdomain enum値でない場合.

    Notes:
        非負の未知mod bitはIntFlagで保持するため変換時にエラーにしない.
    """
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
    """beatmapのsubmission数とpass数を集計するselectを作る.

    Args:
        beatmap_id (int): 集計対象beatmapの永続化識別子.

    Returns:
        Select[tuple[int, int]]: 全score数とpassed score数を返すSQLAlchemy select.
    """
    return select(
        func.count(ScoreModel.id),
        func.coalesce(
            func.sum(case((ScoreModel.passed.is_(True), 1), else_=0)),
            0,
        ),
    ).where(ScoreModel.beatmap_id == beatmap_id)


def _count_value(value: object) -> int:
    """Database aggregate結果をboolではない整数countへ絞り込む.

    Args:
        value (object): SQLAlchemy result rowから取り出した集計値.

    Returns:
        int: boolを除外して検証済みの整数count.

    Raises:
        TypeError: valueがboolまたは整数以外の場合.
    """
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
    """指定scopeのinitial UserStats入力scoreを取得するselectを作る.

    Args:
        user_id (int): scoreを取得するuserの永続化識別子.
        ruleset (Ruleset): 取得対象のruleset.
        playstyle (Playstyle): 取得対象のplaystyle.

    Returns:
        Select[tuple[ScoreModel]]: 時系列順の対象scoreを返すSQLAlchemy select.

    Notes:
        RELAXとAUTOPILOT modを含むscoreはwhere条件で除外する.
    """
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
    """Initial UserStatsから除外するmod bitmask条件を作る.

    Returns:
        ColumnElement[bool]: RELAXとAUTOPILOTの両方が未設定であることを示すSQL条件.
    """
    return ScoreModel.mods.bitwise_and(_EXCLUDED_INITIAL_STATS_MODS) == literal(0)


def _leaderboard_rebuild_candidate_statement() -> Select[tuple[ScoreModel]]:
    """Leaderboard projection再構築候補を決定的順序で取得するselectを作る.

    Returns:
        Select[tuple[ScoreModel]]: leaderboard適格scoreを返すSQLAlchemy select.

    Notes:
        passedかつeligibleでcurrent beatmap checksumと一致するscoreだけを対象とする.
        sort keyはbeatmapとrulesetとplaystyleとuserとscoreとsubmission時刻とidの順序を固定する.
    """
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
