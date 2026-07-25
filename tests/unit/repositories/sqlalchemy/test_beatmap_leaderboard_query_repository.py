"""SQLAlchemy Beatmap Leaderboard query persistenceを検証する."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast, override

from sqlalchemy.dialects import postgresql

from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    LeaderboardReadScope,
)
from osu_server.repositories.sqlalchemy.queries.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardQueryRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from types import TracebackType

    from sqlalchemy.sql.elements import ClauseElement

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_NOW = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)
_BEATMAP_ID = 75
_CURRENT_CHECKSUM = "a" * 32


class FakeResult:
    """mapping rowを返すSQLAlchemy result test double.

    Attributes:
        _rows (list[Mapping[str, object]]): mappings().all()が返すrow群.
    """

    _rows: list[Mapping[str, object]]

    def __init__(self, rows: Iterable[Mapping[str, object]] = ()) -> None:
        """Mapping row群を持つresult test doubleを初期化する.

        Args:
            rows (Iterable[Mapping[str, object]]): query resultとして返すmapping row群.
        """
        self._rows = list(rows)

    def mappings(self) -> FakeResult:
        """Mapping row access用にこのresultを返す.

        Returns:
            FakeResult: mappings().all()呼び出しを受け付けるこのtest double.
        """
        return self

    def all(self) -> list[Mapping[str, object]]:
        """設定済みのmapping row群を返す.

        Returns:
            list[Mapping[str, object]]: query resultとして設定されたmapping row群.
        """
        return self._rows


class FakeQuerySession(AbstractAsyncContextManager["FakeQuerySession"]):
    """query repository readを再現しmutation APIを拒否するAsyncSession test double.

    Attributes:
        closed (bool): context終了後にsessionが閉じられたか.
        statements (list[ClauseElement]): 実行されたread statement.
        _execute_results (list[FakeResult]): executeごとに返すresult test double.
    """

    closed: bool
    statements: list[ClauseElement]
    _execute_results: list[FakeResult]

    def __init__(self, execute_results: Iterable[FakeResult] = ()) -> None:
        """read結果列を受け取るquery session test doubleを初期化する.

        Args:
            execute_results (Iterable[FakeResult]): executeごとに順番に返すresult群.
        """
        self.closed = False
        self.statements = []
        self._execute_results = list(execute_results)

    @override
    async def __aenter__(self) -> FakeQuerySession:
        """context内で使用するquery sessionを返す.

        Returns:
            FakeQuerySession: read statementを記録するこのsession.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """context終了時にquery sessionを閉じる.

        Args:
            exc_type (type[BaseException] | None): context内で送出された例外の型.
                例外がない場合はNone.
            exc (BaseException | None): context内で送出された例外. 例外がない場合はNone.
            traceback (TracebackType | None): 例外のtraceback. 例外がない場合はNone.

        Returns:
            None: sessionを閉じて例外を抑制せずに完了する.
        """
        _ = exc_type
        _ = exc
        _ = traceback
        await self.close()

    async def execute(self, statement: ClauseElement) -> FakeResult:
        """Read statementを記録し次の設定済みresultを返す.

        Args:
            statement (ClauseElement): query repositoryが実行するread statement.

        Returns:
            FakeResult: 次の設定済みresult. 設定がなければ空result.
        """
        self.statements.append(statement)
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult()

    def add(self, instance: object) -> None:
        """Query repositoryによるaddを拒否する.

        Args:
            instance (object): add対象として渡されたinstance.

        Returns:
            None: mutationを実行せず例外送出で完了する.

        Raises:
            AssertionError: query repositoryがaddを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not add instances")

    async def delete(self, instance: object) -> None:
        """Query repositoryによるdeleteを拒否する.

        Args:
            instance (object): delete対象として渡されたinstance.

        Returns:
            None: mutationを実行せず例外送出で完了する.

        Raises:
            AssertionError: query repositoryがdeleteを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not delete instances")

    async def merge(self, instance: object) -> object:
        """Query repositoryによるmergeを拒否する.

        Args:
            instance (object): merge対象として渡されたinstance.

        Returns:
            object: mutationを拒否するため正常には返さない値.

        Raises:
            AssertionError: query repositoryがmergeを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not merge instances")

    async def flush(self) -> None:
        """Query repositoryによるflushを拒否する.

        Returns:
            None: mutationを実行せず例外送出で完了する.

        Raises:
            AssertionError: query repositoryがflushを呼び出した場合.
        """
        raise AssertionError("query repository must not flush")

    async def commit(self) -> None:
        """Query repositoryによるcommitを拒否する.

        Returns:
            None: transactionを確定せず例外送出で完了する.

        Raises:
            AssertionError: query repositoryがcommitを呼び出した場合.
        """
        raise AssertionError("query repository must not commit")

    async def rollback(self) -> None:
        """Query repositoryによるrollbackを拒否する.

        Returns:
            None: transactionをrollbackせず例外送出で完了する.

        Raises:
            AssertionError: query repositoryがrollbackを呼び出した場合.
        """
        raise AssertionError("query repository must not rollback")

    async def refresh(self, instance: object) -> None:
        """Query repositoryによるrefreshを拒否する.

        Args:
            instance (object): refresh対象として渡されたinstance.

        Returns:
            None: mutationを実行せず例外送出で完了する.

        Raises:
            AssertionError: query repositoryがrefreshを呼び出した場合.
        """
        _ = instance
        raise AssertionError("query repository must not refresh")

    async def close(self) -> None:
        """sessionを閉じた状態として記録する.

        Returns:
            None: closedをTrueにして呼び出し側へ値を返さずに完了する.
        """
        self.closed = True


class FakeSessionFactory:
    """同じquery sessionを返しfactory利用回数を記録するtest double.

    Attributes:
        session (FakeQuerySession): factoryが返すquery session.
        calls (int): factoryが呼び出された回数.
    """

    session: FakeQuerySession
    calls: int

    def __init__(self, session: FakeQuerySession) -> None:
        """返却するquery sessionを持つfactory test doubleを初期化する.

        Args:
            session (FakeQuerySession): repositoryがcontext管理するquery session.
        """
        self.session = session
        self.calls = 0

    def __call__(self) -> FakeQuerySession:
        """factory利用回数を増やして設定済みsessionを返す.

        Returns:
            FakeQuerySession: repositoryがreadに使用する設定済みsession.
        """
        self.calls += 1
        return self.session


async def test_top_rows_rank_mod_scoped_projection_and_map_source_rows() -> None:
    """Mod scopeのprojectionを順位付けしsource rowへmapするquery契約を検証する.

    Returns:
        None: row mappingとread SQLとsession closeを検証して完了する.

    Raises:
        AssertionError: visible rowまたはranking SQLまたはsession lifecycleが異なる場合.
    """
    session = FakeQuerySession(
        [FakeResult([_row(score_id=10, user_id=20, score=2_000_000, pp=Decimal("123.456"))])]
    )
    repository = _repository(session)

    rows = await repository.list_top_rows(_scope(), limit=100)

    assert len(rows) == 1
    row = rows[0]
    assert row.score_id == 10
    assert row.user_id == 20
    assert row.username == "User20"
    assert row.ruleset is Ruleset.OSU
    assert row.playstyle is Playstyle.VANILLA
    assert row.score == 2_000_000
    assert row.hit_counts.n300 == 300
    assert row.displayed_mods == ModCombination.none()
    assert row.rank == 1
    assert row.has_replay is True
    assert row.pp == Decimal("123.456")
    assert session.closed is True

    sql = _compiled_sql(session.statements[0])
    assert "FROM beatmap_leaderboard_user_bests" in sql
    assert "JOIN scores" in sql
    assert "JOIN beatmaps" in sql
    assert "JOIN users" in sql
    assert "LEFT OUTER JOIN score_performance_calculations" in sql
    assert "LEFT OUTER JOIN" in sql
    assert "role_permissions" in sql
    assert "row_number() OVER" in sql
    assert "PARTITION BY beatmap_leaderboard_user_bests.user_id" in sql
    assert "ORDER BY scores.score DESC" in sql
    assert "scores.submitted_at ASC" in sql
    assert "scores.id ASC" in sql
    assert "scores.user_id = beatmap_leaderboard_user_bests.user_id" in sql
    assert "scores.mods = beatmap_leaderboard_user_bests.mods" in sql
    assert "scores.beatmap_checksum = beatmap_leaderboard_user_bests.beatmap_checksum" in sql
    assert "beatmaps.checksum_md5" in sql
    assert "scores.beatmap_checksum" in sql
    assert "scores.passed IS true" in sql
    assert "scores.leaderboard_eligible_at_submission IS true" in sql
    assert "bit_or(roles.permissions)" in sql
    assert "&" in sql
    assert "EXISTS (SELECT replay_file_attachments.id" in sql
    assert "CASE WHEN" in sql
    assert "score_performance_calculations.pp" in sql


async def test_personal_best_uses_same_filtered_window_ordering_as_top_rows() -> None:
    """Personal bestがtop rowsと同じfiltered window orderingを使う契約を検証する.

    Returns:
        None: 全体rankとtop rows共通のSQL predicateを検証して完了する.

    Raises:
        AssertionError: personal best rowまたはfiltered window SQLが異なる場合.
    """
    session = FakeQuerySession(
        [
            FakeResult([_row(score_id=1, user_id=1, score=3_000_000, rank=1)]),
            FakeResult([_row(score_id=52, user_id=52, score=1_000_000, rank=52)]),
        ]
    )
    repository = _repository(session)

    rows = await repository.list_top_rows(_scope(), limit=50)
    personal_best = await repository.get_personal_best(_scope(), viewer_user_id=52)

    assert [row.rank for row in rows] == [1]
    assert personal_best is not None
    assert personal_best.score_id == 52
    assert personal_best.rank == 52
    assert session.closed is True

    top_sql = _compiled_sql(session.statements[0])
    personal_best_sql = _compiled_sql(session.statements[1])
    for sql in (top_sql, personal_best_sql):
        assert "row_number() OVER" in sql
        assert "FROM beatmap_leaderboard_user_bests" in sql
        assert "scores.passed IS true" in sql
        assert "scores.leaderboard_eligible_at_submission IS true" in sql
        assert "PARTITION BY beatmap_leaderboard_user_bests.user_id" in sql
        assert "ORDER BY scores.score DESC" in sql
        assert "scores.submitted_at ASC" in sql
        assert "scores.id ASC" in sql
        assert "scores.user_id = beatmap_leaderboard_user_bests.user_id" in sql
        assert "scores.mods = beatmap_leaderboard_user_bests.mods" in sql
    assert "ranked_candidates.rank <= " in top_sql
    assert "ranked_candidates.user_id = " in personal_best_sql


async def test_only_selected_mods_category_applies_exact_raw_mods() -> None:
    """SELECTED_MODSだけがraw Modの完全一致predicateを使うcategory契約を検証する.

    Returns:
        None: countryとfriendsとselected ModsのSQL filter差分を検証して完了する.

    Raises:
        AssertionError: category別のpredicateまたはraw Mod比較方法が異なる場合.
    """
    country_session = FakeQuerySession()
    country_repository = _repository(country_session)
    _ = await country_repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.COUNTRY,
            country="JP",
        ),
        limit=50,
    )

    friends_session = FakeQuerySession()
    friends_repository = _repository(friends_session)
    _ = await friends_repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.FRIENDS,
            eligible_user_ids=(10, 11),
        ),
        limit=50,
    )

    selected_mods_session = FakeQuerySession()
    selected_mods_repository = _repository(selected_mods_session)
    _ = await selected_mods_repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.SELECTED_MODS,
            selected_mods=ModCombination(Mod.DOUBLE_TIME),
        ),
        limit=50,
    )

    country_sql = _compiled_sql(country_session.statements[0])
    friends_sql = _compiled_sql(friends_session.statements[0])
    selected_mods_sql = _compiled_sql(selected_mods_session.statements[0])
    double_time_bit = int(Mod.DOUBLE_TIME)
    assert "beatmap_leaderboard_user_bests.mods = " not in country_sql
    assert "users.country = " in country_sql
    assert "beatmap_leaderboard_user_bests.mods = " not in friends_sql
    assert "users.id IN " in friends_sql
    assert f"beatmap_leaderboard_user_bests.mods = {double_time_bit}" in selected_mods_sql
    assert "&" not in selected_mods_sql.split("ranked_user_scores", maxsplit=1)[0]
    assert "users.country = " not in selected_mods_sql


async def test_nullable_pp_does_not_hide_rows_and_pp_sql_is_ranked_approved_only() -> None:
    """Nullable PPがrowを隠さずPP表示がranked/approved statusに限られる契約を検証する.

    Returns:
        None: nullable PP rowとbeatmap status SQL条件を検証して完了する.

    Raises:
        AssertionError: nullable PP rowまたはPP表示status条件が異なる場合.
    """
    session = FakeQuerySession(
        [
            FakeResult(
                [
                    _row(score_id=10, user_id=10, score=2_000_000, pp=Decimal("250.125")),
                    _row(score_id=11, user_id=11, score=1_900_000, pp=None, rank=2),
                    _row(score_id=12, user_id=12, score=1_800_000, pp=None, rank=3),
                ]
            )
        ]
    )
    repository = _repository(session)

    rows = await repository.list_top_rows(_scope(), limit=50)

    assert [row.score_id for row in rows] == [10, 11, 12]
    assert [row.pp for row in rows] == [Decimal("250.125"), None, None]
    sql = _compiled_sql(session.statements[0])
    assert "CASE WHEN" in sql
    assert "'ranked'" in sql
    assert "'approved'" in sql
    assert "'loved'" in sql
    assert "'qualified'" in sql


def _repository(
    session: FakeQuerySession,
) -> SQLAlchemyBeatmapLeaderboardQueryRepository:
    """Test query sessionをquery repositoryへ型適合させて構築する.

    Args:
        session (FakeQuerySession): read statementとclose状態を記録するtest session.

    Returns:
        SQLAlchemyBeatmapLeaderboardQueryRepository: test session factoryを持つquery repository.
    """
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    return SQLAlchemyBeatmapLeaderboardQueryRepository(session_factory)


def _scope(
    *,
    category: LeaderboardCategory = LeaderboardCategory.GLOBAL,
    selected_mods: ModCombination | None = None,
    country: str | None = None,
    eligible_user_ids: tuple[int, ...] | None = None,
) -> LeaderboardReadScope:
    """Category filterを含むleaderboard read scopeを既定値で構築する.

    Args:
        category (LeaderboardCategory): 適用するleaderboard category filter.
        selected_mods (ModCombination | None): SELECTED_MODS categoryで完全一致比較するMod値.
        country (str | None): COUNTRY categoryで一致させる国code.
        eligible_user_ids (tuple[int, ...] | None): FRIENDS categoryで許可するuser ID群.

    Returns:
        LeaderboardReadScope: 指定したcategory filterを含むbeatmap read scope.
    """
    return LeaderboardReadScope(
        beatmap_id=_BEATMAP_ID,
        beatmap_checksum=_CURRENT_CHECKSUM,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=category,
        selected_mods=selected_mods,
        country=country,
        eligible_user_ids=eligible_user_ids,
    )


def _row(
    *,
    score_id: int,
    user_id: int,
    score: int,
    rank: int = 1,
    pp: Decimal | None = None,
) -> Mapping[str, object]:
    """repositoryがdomain rowへ変換するSQL mapping rowを構築する.

    Args:
        score_id (int): source scoreの識別子.
        user_id (int): source scoreを送信したuserの識別子.
        score (int): rankingに使うscore値.
        rank (int): rowに設定する全体順位.
        pp (Decimal | None): 表示対象のperformance point. 非表示時はNone.

    Returns:
        Mapping[str, object]: leaderboard row conversionに必要なfieldを持つmapping.
    """
    return {
        "score_id": score_id,
        "user_id": user_id,
        "username": f"User{user_id}",
        "beatmap_id": _BEATMAP_ID,
        "ruleset": Ruleset.OSU.value,
        "playstyle": Playstyle.VANILLA.value,
        "score": score,
        "max_combo": 1_234,
        "n50": 1,
        "n100": 10,
        "n300": 300,
        "miss": 0,
        "katu": 5,
        "geki": 50,
        "perfect": True,
        "displayed_mods": ModCombination.none().to_persistence_bitmask(),
        "rank": rank,
        "submitted_at": _NOW,
        "has_replay": True,
        "pp": pp,
    }


def _compiled_sql(statement: ClauseElement) -> str:
    """SQLAlchemy statementをliteral bind付きPostgreSQL SQLへコンパイルする.

    Args:
        statement (ClauseElement): SQL構造を検証する対象statement.

    Returns:
        str: literal bindを展開したPostgreSQL dialectのSQL文字列.
    """
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
