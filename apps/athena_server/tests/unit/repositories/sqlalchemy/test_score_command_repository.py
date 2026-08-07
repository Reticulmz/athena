"""SQLAlchemy score command repositoryの永続化契約を検証するtests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.repositories.sqlalchemy.commands.scores import SQLAlchemyScoreCommandRepository
from osu_server.repositories.sqlalchemy.models.score import ScoreModel

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession


class FakeExecuteResult:
    """score query結果を再現するSQLAlchemy execute result fakeを表す.

    Attributes:
        _models (tuple[ScoreModel, ...]): scalarsから返すscore model列.
        _row (tuple[int, int]): oneから返すplay countとpass count.
        _value (object | None): scalar_one_or_noneから返す値.
    """

    def __init__(
        self,
        models: tuple[ScoreModel, ...] = (),
        row: tuple[int, int] = (0, 0),
        value: object | None = None,
    ) -> None:
        """query結果を指定してexecute result fakeを初期化する.

        Args:
            models (tuple[ScoreModel, ...]): scalar iterationで返すscore model列.
            row (tuple[int, int]): submission count queryで返すplay countとpass count.
            value (object | None): scalar queryで返す値. 結果がない場合はNone.
        """
        self._models: tuple[ScoreModel, ...] = models
        self._row: tuple[int, int] = row
        self._value: object | None = value

    def scalars(self) -> tuple[ScoreModel, ...]:
        """設定済みscore model列を返す.

        Returns:
            tuple[ScoreModel, ...]: scalar resultとして扱うscore model列.
        """
        return self._models

    def one(self) -> tuple[int, int]:
        """設定済みのplay countとpass countを返す.

        Returns:
            tuple[int, int]: submission集計用のplay countとpass count.
        """
        return self._row

    def scalar_one_or_none(self) -> object | None:
        """設定済みのscalar値またはNoneを返す.

        Returns:
            object | None: queryのscalar結果. 結果がない場合はNone.
        """
        return self._value


class FakeSession:
    """score command repositoryのmappingを検証するAsyncSession fakeを表す.

    Attributes:
        added_model (ScoreModel | None): addで受け取ったscore model.
        statements (list[object]): executeで受け取ったSQL statement.
        execute_row (tuple[int, int]): execute resultのcount row.
        execute_value (object | None): execute resultのscalar値.
        flushes (int): flushの呼び出し回数.
    """

    def __init__(self) -> None:
        """空のscore command session fakeを初期化する."""
        self.added_model: ScoreModel | None = None
        self.statements: list[object] = []
        self.execute_row: tuple[int, int] = (0, 0)
        self.execute_value: object | None = None
        self.flushes: int = 0

    def add(self, instance: object) -> None:
        """受け取ったscore model追加を記録する.

        Args:
            instance (object): repositoryが追加するscore model.

        Returns:
            None: 追加modelを記録して呼び出し側へ値を返さずに完了する.

        Raises:
            AssertionError: repositoryがScoreModel以外を追加した場合.
        """
        assert isinstance(instance, ScoreModel)
        self.added_model = instance

    async def execute(self, statement: object) -> FakeExecuteResult:
        """SQL statementを記録して設定済みexecute resultを返す.

        Args:
            statement (object): repositoryが発行するSQL statement.

        Returns:
            FakeExecuteResult: countとscalar値を供給するresult fake.
        """
        self.statements.append(statement)
        return FakeExecuteResult(row=self.execute_row, value=self.execute_value)

    async def flush(self) -> None:
        """未flushのscore modelへ固定IDを割り当ててflushを記録する.

        Returns:
            None: flush回数とscore IDを更新して呼び出し側へ値を返さずに完了する.
        """
        self.flushes += 1
        if self.added_model is not None:
            self.added_model.id = 42

    async def refresh(self, instance: object) -> None:
        """追加済みscore modelだけをrefresh対象として受け入れる.

        Args:
            instance (object): repositoryがrefreshするscore model.

        Returns:
            None: 対象identityを検証して呼び出し側へ値を返さずに完了する.

        Raises:
            AssertionError: 追加済みmodel以外をrefreshした場合.
        """
        assert instance is self.added_model


async def test_create_persists_leaderboard_eligibility_snapshot() -> None:
    """非eligible scoreを作成する条件でeligibility snapshotを保存する契約を検証する.

    Returns:
        None: modelとdomain resultのeligibility値を検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    created = await repository.create(_score(leaderboard_eligible_at_submission=False))

    assert session.added_model is not None
    assert session.added_model.leaderboard_eligible_at_submission is False
    assert created.leaderboard_eligible_at_submission is False


async def test_create_exposes_zero_replay_view_count_for_new_score() -> None:
    """新規scoreを作成する条件でreplay view countを0にする契約を検証する.

    Returns:
        None: modelとdomain resultの初期view countを検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    created = await repository.create(_score(leaderboard_eligible_at_submission=False))

    assert session.added_model is not None
    assert session.added_model.replay_view_count == 0
    assert created.replay_view_count == 0


async def test_create_persists_timing_fields() -> None:
    """失敗時timingを持つscoreを作成する条件で全timing fieldを保存する契約を検証する.

    Returns:
        None: modelとdomain resultのtiming fieldを検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    created = await repository.create(
        replace(
            _score(leaderboard_eligible_at_submission=False),
            fail_time_ms=7_112,
            play_time_seconds=7,
            play_time_source=PlayTimeSource.FAIL_TIME,
            submit_exit_classification="1",
        )
    )

    assert session.added_model is not None
    assert session.added_model.fail_time_ms == 7_112
    assert session.added_model.play_time_seconds == 7
    assert session.added_model.play_time_source == "fail_time"
    assert session.added_model.submit_exit_classification == "1"
    assert created.fail_time_ms == 7_112
    assert created.play_time_seconds == 7
    assert created.play_time_source is PlayTimeSource.FAIL_TIME
    assert created.submit_exit_classification == "1"


async def test_user_rebuild_candidates_select_only_passed_submission_eligible_scores() -> None:
    """特定userのrebuild候補がeligible passed scoreだけを選ぶSQLを検証する.

    Returns:
        None: filterと安定sortを含むcompiled SQLを検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_leaderboard_rebuild_candidates_for_user(1000)

    assert result == ()
    sql = _compiled_select(session.statements[0])
    assert "scores.user_id = %(user_id_1)s" in sql
    assert "scores.passed IS true" in sql
    assert "scores.leaderboard_eligible_at_submission IS true" in sql
    assert "ORDER BY scores.beatmap_id ASC" in sql
    assert "scores.score DESC" in sql
    assert "scores.submitted_at ASC" in sql
    assert "scores.id ASC" in sql


async def test_beatmap_rebuild_candidates_select_target_beatmap_ids() -> None:
    """対象beatmap ID列でrebuild候補を取得する条件で対象scoreだけを選ぶSQLを検証する.

    Returns:
        None: beatmap ID filterとeligibility filterを検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_leaderboard_rebuild_candidates_for_beatmap_ids((1, 2))

    assert result == ()
    sql = _compiled_select(session.statements[0])
    assert "scores.beatmap_id IN (__[POSTCOMPILE_beatmap_id_1])" in sql
    assert "scores.passed IS true" in sql
    assert "scores.leaderboard_eligible_at_submission IS true" in sql


async def test_current_stats_scores_select_user_mode_and_exclude_relax_autopilot() -> None:
    """統計用scoreを取得する条件でuser mode filterとrelax除外を行うSQLを検証する.

    Returns:
        None: userとmode predicateを含むcompiled SQLを検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_current_stats_scores_for_user(
        1000,
        ruleset=Ruleset.MANIA,
        playstyle=Playstyle.VANILLA,
    )

    assert result == ()
    sql = _compiled_select(session.statements[0])
    assert "scores.user_id = %(user_id_1)s" in sql
    assert "scores.ruleset = %(ruleset_1)s" in sql
    assert "scores.playstyle = %(playstyle_1)s" in sql
    assert "& %(mods_1)s" in sql
    assert "ORDER BY scores.submitted_at ASC" in sql


async def test_empty_beatmap_candidate_selection_does_not_query() -> None:
    """空のbeatmap ID列を渡す条件でqueryを発行しない契約を検証する.

    Returns:
        None: 空のresultと未実行statementを検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.list_leaderboard_rebuild_candidates_for_beatmap_ids(())

    assert result == ()
    assert session.statements == []


async def test_count_submissions_for_beatmap_selects_play_and_pass_counts() -> None:
    """対象beatmapのsubmissionを集計する条件でplay countとpass countを返すSQLを検証する.

    Returns:
        None: 集計resultとcompiled SQLのcount predicateを検証して完了する.
    """
    session = FakeSession()
    session.execute_row = (3, 2)
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.count_submissions_for_beatmap(100)

    assert result.play_count == 3
    assert result.pass_count == 2
    sql = _compiled_select(session.statements[0])
    assert "count(scores.id)" in sql
    assert "CASE WHEN (scores.passed IS true)" in sql
    assert "scores.beatmap_id = %(beatmap_id_1)s" in sql


async def test_increment_replay_view_count_uses_atomic_update_returning() -> None:
    """既存scoreのreplay viewを増やす条件でatomic update returningを使う契約を検証する.

    Returns:
        None: successful resultと1回のflushを含むcompiled SQLを検証して完了する.
    """
    session = FakeSession()
    session.execute_value = 42
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.increment_replay_view_count(42)

    assert result is True
    assert session.flushes == 1
    assert len(session.statements) == 1
    sql = _compiled_clause(session.statements[0])
    assert "UPDATE scores SET" in sql
    assert "replay_view_count=(scores.replay_view_count + " in sql
    assert "WHERE scores.id = " in sql
    assert "RETURNING scores.id" in sql


async def test_increment_replay_view_count_returns_false_when_score_missing() -> None:
    """存在しないscoreのreplay viewを増やす条件でFalseを返す契約を検証する.

    Returns:
        None: missing resultとflush回数を検証して完了する.
    """
    session = FakeSession()
    repository = SQLAlchemyScoreCommandRepository(cast("AsyncSession", cast("object", session)))

    result = await repository.increment_replay_view_count(404)

    assert result is False
    assert session.flushes == 1


def _score(*, leaderboard_eligible_at_submission: bool) -> Score:
    """test用のdomain scoreを作成する.

    Args:
        leaderboard_eligible_at_submission (bool): submission時点でleaderboard対象か.

    Returns:
        Score: 指定eligibilityを持つ永続化対象のscore.
    """
    return Score(
        id=None,
        user_id=1000,
        beatmap_id=1,
        beatmap_checksum="abc123",
        online_checksum="online-checksum",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=100,
        n100=10,
        n50=5,
        geki=0,
        katu=0,
        miss=2,
        score=500000,
        max_combo=99,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="20240101",
        submitted_at=datetime.now(UTC),
        beatmap_status_at_submission=BeatmapRankStatus.PENDING,
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
    )


def _compiled_select(statement: object) -> str:
    """対象score select statementをPostgreSQL SQL文字列へcompileする.

    Args:
        statement (object): selectとして期待するrepository statement.

    Returns:
        str: assertionに使うcompiled PostgreSQL SQL.
    """
    typed_statement = cast("Select[tuple[ScoreModel]]", statement)
    return str(typed_statement.compile(dialect=postgresql.dialect()))


def _compiled_clause(statement: object) -> str:
    """対象score update clauseをPostgreSQL SQL文字列へcompileする.

    Args:
        statement (object): ClauseElementとして期待するrepository statement.

    Returns:
        str: assertionに使うcompiled PostgreSQL SQL.

    Raises:
        AssertionError: statementがClauseElementではない場合.
    """
    assert isinstance(statement, ClauseElement)
    return str(statement.compile(dialect=postgresql.dialect()))
