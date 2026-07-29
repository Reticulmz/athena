"""SQLAlchemy replay download query repositoryの永続化境界を検証するtests."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast, override

from sqlalchemy.dialects import postgresql

from osu_server.domain.scores.score import Ruleset
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidateKind,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
    ReplayDownloadMissingReplayCandidate,
    ReplayDownloadScoreNotFoundCandidate,
)
from osu_server.repositories.sqlalchemy.queries.replay_download import (
    SQLAlchemyReplayDownloadQueryRepository,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from types import TracebackType

    from sqlalchemy.sql.elements import ClauseElement

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory


class FakeResult:
    """mapping rowを返すSQLAlchemy resultのtest doubleを表す.

    Attributes:
        _rows (list[Mapping[str, object]]): candidate queryへ返すmapping row.
    """

    _rows: list[Mapping[str, object]]

    def __init__(self, rows: Iterable[Mapping[str, object]] = ()) -> None:
        """候補query用のmapping rowを保存するfakeを初期化する.

        Args:
            rows (Iterable[Mapping[str, object]]): query実行時に返すmapping row.
        """
        self._rows = list(rows)

    def mappings(self) -> FakeResult:
        """対応するmapping APIを継続して使うためにこのfakeを返す.

        Returns:
            FakeResult: mapping rowを参照するこのresult fake.
        """
        return self

    def one_or_none(self) -> Mapping[str, object] | None:
        """0件または1件のmapping rowを返す.

        Returns:
            Mapping[str, object] | None: 唯一のrow. rowがない場合はNone.

        Raises:
            AssertionError: candidate queryが2件以上のrowを返した場合.
        """
        if len(self._rows) > 1:
            raise AssertionError("candidate query must return at most one row")
        return self._rows[0] if self._rows else None


class FakeQuerySession(AbstractAsyncContextManager["FakeQuerySession"]):
    """query repositoryのread-only契約を検証するAsyncSession fakeを表す.

    Attributes:
        closed (bool): context終了時にcloseされたか.
        mutation_calls (list[str]): 禁止したmutation APIの呼び出し順.
        statements (list[ClauseElement]): executeへ渡されたSQL statement.
        _execute_results (list[FakeResult]): executeから順に返すresult fake.
    """

    closed: bool
    mutation_calls: list[str]
    statements: list[ClauseElement]
    _execute_results: list[FakeResult]

    def __init__(self, execute_results: Iterable[FakeResult] = ()) -> None:
        """read-only session fakeを初期化する.

        Args:
            execute_results (Iterable[FakeResult]): executeから順に返すresult fake.
        """
        self.closed = False
        self.mutation_calls = []
        self.statements = []
        self._execute_results = list(execute_results)

    @override
    async def __aenter__(self) -> FakeQuerySession:
        """query実行に使用するこのsession fakeを返す.

        Returns:
            FakeQuerySession: context内で利用するread-only session fake.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """context終了時にsession fakeをcloseする.

        Args:
            exc_type (type[BaseException] | None): contextから伝播するexceptionの型.
            exc (BaseException | None): contextから伝播するexception instance.
            traceback (TracebackType | None): contextから伝播するtraceback.

        Returns:
            None: sessionをcloseして呼び出し側へ値を返さずに完了する.
        """
        _ = exc_type
        _ = exc
        _ = traceback
        await self.close()

    async def execute(self, statement: ClauseElement) -> FakeResult:
        """read-only query statementを記録して設定済みresultを返す.

        Args:
            statement (ClauseElement): repositoryが発行するSQL query statement.

        Returns:
            FakeResult: 設定済みの次のresult. 未設定時は空のresult.
        """
        self.statements.append(statement)
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult()

    def add(self, instance: object) -> None:
        """読み取りquery repositoryによるadd呼び出しを失敗として記録する.

        Args:
            instance (object): 追加しようとした永続化instance.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがaddを実行した場合.
        """
        _ = instance
        self.mutation_calls.append("add")
        raise AssertionError("query repository must not add instances")

    async def delete(self, instance: object) -> None:
        """読み取りquery repositoryによるdelete呼び出しを失敗として記録する.

        Args:
            instance (object): 削除しようとした永続化instance.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがdeleteを実行した場合.
        """
        _ = instance
        self.mutation_calls.append("delete")
        raise AssertionError("query repository must not delete instances")

    async def merge(self, instance: object) -> object:
        """読み取りquery repositoryによるmerge呼び出しを失敗として記録する.

        Args:
            instance (object): mergeしようとした永続化instance.

        Raises:
            AssertionError: query repositoryがmergeを実行した場合.
        """
        _ = instance
        self.mutation_calls.append("merge")
        raise AssertionError("query repository must not merge instances")

    async def flush(self) -> None:
        """読み取りquery repositoryによるflush呼び出しを失敗として記録する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがflushを実行した場合.
        """
        self.mutation_calls.append("flush")
        raise AssertionError("query repository must not flush")

    async def commit(self) -> None:
        """読み取りquery repositoryによるcommit呼び出しを失敗として記録する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがcommitを実行した場合.
        """
        self.mutation_calls.append("commit")
        raise AssertionError("query repository must not commit")

    async def rollback(self) -> None:
        """読み取りquery repositoryによるrollback呼び出しを失敗として記録する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがrollbackを実行した場合.
        """
        self.mutation_calls.append("rollback")
        raise AssertionError("query repository must not rollback")

    async def refresh(self, instance: object) -> None:
        """読み取りquery repositoryによるrefresh呼び出しを失敗として記録する.

        Args:
            instance (object): refreshしようとした永続化instance.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            AssertionError: query repositoryがrefreshを実行した場合.
        """
        _ = instance
        self.mutation_calls.append("refresh")
        raise AssertionError("query repository must not refresh")

    async def close(self) -> None:
        """このsession fakeをclose済みにしてread-only contextの終了を表す.

        Returns:
            None: close状態を記録して呼び出し側へ値を返さずに完了する.
        """
        self.closed = True


class FakeSessionFactory:
    """同一read-only sessionを供給するquery session factory fakeを表す.

    Attributes:
        session (FakeQuerySession): factoryから返すread-only session fake.
        calls (int): factoryが呼び出された回数.
    """

    session: FakeQuerySession
    calls: int

    def __init__(self, session: FakeQuerySession) -> None:
        """返却するsession fakeを指定してfactoryを初期化する.

        Args:
            session (FakeQuerySession): query実行へ供給するread-only session fake.
        """
        self.session = session
        self.calls = 0

    def __call__(self) -> FakeQuerySession:
        """factory使用回数を増やして同一session fakeを返す.

        Returns:
            FakeQuerySession: query実行に使用するread-only session fake.
        """
        self.calls += 1
        return self.session


async def test_get_candidate_returns_score_not_found_for_id_ruleset_miss() -> None:
    """対象score idとrulesetが一致しない条件でscore not found候補を返す契約を検証する.

    Returns:
        None: 欠落候補のkindを検証して呼び出し側へ値を返さずに完了する.
    """
    session = FakeQuerySession([FakeResult()])
    repository = _repository(session)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=999, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadScoreNotFoundCandidate)
    assert result.kind is ReplayDownloadCandidateKind.SCORE_NOT_FOUND


async def test_get_candidate_keeps_hidden_score_separate_from_missing_replay() -> None:
    """非公開scoreにattachmentがある条件でhidden score候補を返す契約を検証する.

    Returns:
        None: missing replayと区別したcandidate kindを検証して完了する.
    """
    session = FakeQuerySession(
        [
            FakeResult(
                [
                    _row(
                        replay_download_visible=False,
                        blob_id=123,
                        checksum="a" * 64,
                        byte_size=4096,
                    )
                ]
            )
        ]
    )
    repository = _repository(session)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=10, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadHiddenScoreCandidate)
    assert result.kind is ReplayDownloadCandidateKind.HIDDEN_SCORE


async def test_get_candidate_returns_missing_replay_for_visible_score_without_attachment() -> None:
    """公開scoreにreplay attachmentがない条件でmissing replay候補を返す契約を検証する.

    Returns:
        None: replay不在を示すcandidate kindを検証して完了する.
    """
    session = FakeQuerySession([FakeResult([_row(replay_download_visible=True)])])
    repository = _repository(session)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=11, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadMissingReplayCandidate)
    assert result.kind is ReplayDownloadCandidateKind.MISSING_REPLAY


async def test_get_candidate_maps_available_replay_metadata_and_uses_short_read_session() -> None:
    """公開replay metadataを取得する条件でshort-lived read sessionを使う契約を検証する.

    Returns:
        None: metadata mappingとsessionのclose状態を検証して完了する.
    """
    session = FakeQuerySession(
        [
            FakeResult(
                [
                    _row(
                        score_id=12,
                        score_owner_user_id=98,
                        replay_download_visible=True,
                        blob_id=456,
                        checksum="b" * 64,
                        byte_size=8192,
                    )
                ]
            )
        ]
    )
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    repository = SQLAlchemyReplayDownloadQueryRepository(session_factory)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=12, ruleset=Ruleset.OSU)
    )

    assert result == ReplayDownloadAvailableReplayCandidate(
        score_id=12,
        score_owner_user_id=98,
        blob_id=456,
        checksum="b" * 64,
        byte_size=8192,
    )
    assert result.kind is ReplayDownloadCandidateKind.AVAILABLE_REPLAY
    assert factory.calls == 1
    assert len(session.statements) == 1
    assert session.closed is True
    assert session.mutation_calls == []


async def test_get_candidate_statement_reads_replay_metadata_without_storage_details() -> None:
    """replay候補queryが必要なmetadataだけを読むSQL contractを検証する.

    Returns:
        None: storage payloadを読まないcompiled SQLを検証して完了する.
    """
    session = FakeQuerySession([FakeResult([_row(replay_download_visible=True)])])
    repository = _repository(session)

    _ = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=50, ruleset=Ruleset.OSU)
    )

    sql = _compiled_sql(session.statements[0])
    assert "FROM scores" in sql
    assert "LEFT OUTER JOIN replay_file_attachments" in sql
    assert "scores.id = 50" in sql
    assert "scores.ruleset = 0" in sql
    assert "scores.user_id" in sql
    assert "scores.passed IS true" in sql
    assert "scores.leaderboard_eligible_at_submission IS true" in sql
    assert "replay_file_attachments.blob_id" in sql
    assert "replay_file_attachments.checksum_sha256" in sql
    assert "replay_file_attachments.byte_size" in sql
    assert "role_permissions" in sql
    assert "bit_or(roles.permissions)" in sql
    assert "blobs" not in sql
    assert "storage_key" not in sql
    assert "payload" not in sql
    assert "raw" not in sql


def _repository(session: FakeQuerySession) -> SQLAlchemyReplayDownloadQueryRepository:
    """指定session fakeを使うreplay download query repositoryを作成する.

    Args:
        session (FakeQuerySession): read-only queryを記録するsession fake.

    Returns:
        SQLAlchemyReplayDownloadQueryRepository: test対象のrepository instance.
    """
    factory = FakeSessionFactory(session)
    session_factory = cast("SQLAlchemyQuerySessionFactory", cast("object", factory))
    return SQLAlchemyReplayDownloadQueryRepository(session_factory)


def _row(
    *,
    replay_download_visible: bool,
    score_id: int = 10,
    score_owner_user_id: int = 20,
    blob_id: int | None = None,
    checksum: str | None = None,
    byte_size: int | None = None,
) -> Mapping[str, object]:
    """候補replay download query用のmapping rowを作成する.

    Args:
        replay_download_visible (bool): replay downloadを許可するscoreか.
        score_id (int): candidate scoreの識別子.
        score_owner_user_id (int): score所有userの識別子.
        blob_id (int | None): attachmentが参照するblobの識別子.
        checksum (str | None): attachment payloadのSHA-256 checksum.
        byte_size (int | None): attachment payloadのbyte数.

    Returns:
        Mapping[str, object]: repository mappingが読むcandidate row.
    """
    return {
        "score_id": score_id,
        "score_owner_user_id": score_owner_user_id,
        "replay_download_visible": replay_download_visible,
        "blob_id": blob_id,
        "checksum": checksum,
        "byte_size": byte_size,
    }


def _compiled_sql(statement: ClauseElement) -> str:
    """bindを展開したPostgreSQL SQL文字列を作成する.

    Args:
        statement (ClauseElement): repositoryが発行したSQL statement.

    Returns:
        str: assertionに使うcompiled PostgreSQL SQL.
    """
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
