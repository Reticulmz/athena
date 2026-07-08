"""Tests for SQLAlchemy replay download query persistence."""

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
    """Small SQLAlchemy result double returning mapping rows."""

    _rows: list[Mapping[str, object]]

    def __init__(self, rows: Iterable[Mapping[str, object]] = ()) -> None:
        self._rows = list(rows)

    def mappings(self) -> FakeResult:
        return self

    def one_or_none(self) -> Mapping[str, object] | None:
        if len(self._rows) > 1:
            raise AssertionError("candidate query must return at most one row")
        return self._rows[0] if self._rows else None


class FakeQuerySession(AbstractAsyncContextManager["FakeQuerySession"]):
    """AsyncSession-shaped fake that fails on mutation APIs."""

    closed: bool
    mutation_calls: list[str]
    statements: list[ClauseElement]
    _execute_results: list[FakeResult]

    def __init__(self, execute_results: Iterable[FakeResult] = ()) -> None:
        self.closed = False
        self.mutation_calls = []
        self.statements = []
        self._execute_results = list(execute_results)

    @override
    async def __aenter__(self) -> FakeQuerySession:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback
        await self.close()

    async def execute(self, statement: ClauseElement) -> FakeResult:
        self.statements.append(statement)
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult()

    def add(self, instance: object) -> None:
        _ = instance
        self.mutation_calls.append("add")
        raise AssertionError("query repository must not add instances")

    async def delete(self, instance: object) -> None:
        _ = instance
        self.mutation_calls.append("delete")
        raise AssertionError("query repository must not delete instances")

    async def merge(self, instance: object) -> object:
        _ = instance
        self.mutation_calls.append("merge")
        raise AssertionError("query repository must not merge instances")

    async def flush(self) -> None:
        self.mutation_calls.append("flush")
        raise AssertionError("query repository must not flush")

    async def commit(self) -> None:
        self.mutation_calls.append("commit")
        raise AssertionError("query repository must not commit")

    async def rollback(self) -> None:
        self.mutation_calls.append("rollback")
        raise AssertionError("query repository must not rollback")

    async def refresh(self, instance: object) -> None:
        _ = instance
        self.mutation_calls.append("refresh")
        raise AssertionError("query repository must not refresh")

    async def close(self) -> None:
        self.closed = True


class FakeSessionFactory:
    session: FakeQuerySession
    calls: int

    def __init__(self, session: FakeQuerySession) -> None:
        self.session = session
        self.calls = 0

    def __call__(self) -> FakeQuerySession:
        self.calls += 1
        return self.session


async def test_get_candidate_returns_score_not_found_for_id_ruleset_miss() -> None:
    session = FakeQuerySession([FakeResult()])
    repository = _repository(session)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=999, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadScoreNotFoundCandidate)
    assert result.kind is ReplayDownloadCandidateKind.SCORE_NOT_FOUND


async def test_get_candidate_keeps_hidden_score_separate_from_missing_replay() -> None:
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
    session = FakeQuerySession([FakeResult([_row(replay_download_visible=True)])])
    repository = _repository(session)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=11, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadMissingReplayCandidate)
    assert result.kind is ReplayDownloadCandidateKind.MISSING_REPLAY


async def test_get_candidate_maps_available_replay_metadata_and_uses_short_read_session() -> None:
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
    return {
        "score_id": score_id,
        "score_owner_user_id": score_owner_user_id,
        "replay_download_visible": replay_download_visible,
        "blob_id": blob_id,
        "checksum": checksum,
        "byte_size": byte_size,
    }


def _compiled_sql(statement: ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
