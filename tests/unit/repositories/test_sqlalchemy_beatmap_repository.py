from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast, override

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileAttachment,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapCommandRepository
from osu_server.repositories.sqlalchemy.commands.beatmaps import (
    BeatmapNotFoundError,
    DuplicateBeatmapChecksumError,
    SQLAlchemyBeatmapCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)

if TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"


class FakeResult:
    _value: object | None
    _values: list[object]
    _row: tuple[object, object] | None

    def __init__(
        self,
        value: object | None = None,
        values: list[object] | None = None,
        row: tuple[object, object] | None = None,
    ) -> None:
        self._value = value
        self._values = values or []
        self._row = row

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def one_or_none(self) -> tuple[object, object] | None:
        return self._row

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[object]:
        return self._values


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    def __init__(
        self,
        *,
        get_results: dict[tuple[type[object], int], object] | None = None,
        execute_results: list[FakeResult] | None = None,
        flush_error: IntegrityError | None = None,
    ) -> None:
        self.get_results: dict[tuple[type[object], int], object] = get_results or {}
        self.execute_results: list[FakeResult] = execute_results or []
        self.flush_error: IntegrityError | None = flush_error
        self.added: list[object] = []
        self.merged: list[object] = []
        self.refreshed: list[object] = []
        self.executed: list[Executable] = []
        self.get_calls: list[tuple[type[object], int, bool]] = []
        self.flushes: int = 0

    @override
    async def __aenter__(self) -> FakeSession:
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

    async def get(
        self,
        model_type: type[object],
        identity: int,
        *,
        populate_existing: bool = False,
    ) -> object | None:
        self.get_calls.append((model_type, identity, populate_existing))
        return self.get_results.get((model_type, identity))

    async def execute(self, statement: Executable) -> FakeResult:
        self.executed.append(statement)
        if not self.execute_results:
            return FakeResult()
        return self.execute_results.pop(0)

    async def merge(self, instance: object) -> object:
        self.merged.append(instance)
        return instance

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        self.flushes += 1

    async def refresh(self, instance: object) -> None:
        if isinstance(instance, BeatmapFileAttachmentModel):
            instance.id = 1
            instance.created_at = _NOW
        if isinstance(instance, BeatmapFetchStateModel):
            instance.id = 1
            instance.updated_at = _NOW
        self.refreshed.append(instance)


def _repo(session: FakeSession) -> SQLAlchemyBeatmapCommandRepository:
    return SQLAlchemyBeatmapCommandRepository(cast("AsyncSession", cast("object", session)))


def _beatmap_model(
    *,
    id: int = 2_000,  # noqa: A002
    checksum_md5: str = _CHECKSUM,
    official_status: str = "ranked",
    local_status_override: str | None = None,
    local_status_override_changed_at: datetime | None = None,
    official_last_updated_at: datetime | None = None,
    play_count: int = 0,
    pass_count: int = 0,
) -> BeatmapModel:
    return BeatmapModel(
        id=id,
        beatmapset_id=1_000,
        checksum_md5=checksum_md5,
        mode="osu",
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source="official",
        official_status_verified=True,
        local_status_override=local_status_override,
        local_status_override_changed_at=local_status_override_changed_at,
        play_count=play_count,
        pass_count=pass_count,
        official_last_updated_at=official_last_updated_at,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _beatmapset_model() -> BeatmapSetModel:
    return BeatmapSetModel(
        id=1_000,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status="ranked",
        official_status_source="official",
        official_status_verified=True,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _attachment_model() -> BeatmapFileAttachmentModel:
    return BeatmapFileAttachmentModel(
        id=1,
        beatmap_id=2_000,
        blob_id=55,
        checksum_md5=_CHECKSUM,
        verified_md5=_CHECKSUM,
        source="official",
        original_filename="2000.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
        created_at=_NOW,
    )


def _fetch_state_model(status: str = "pending_fetch") -> BeatmapFetchStateModel:
    return BeatmapFetchStateModel(
        id=1,
        target_type="metadata:beatmap",
        target_key="2000",
        status=status,
        attempt_count=1,
        last_error=None,
        pending_since=_NOW,
        last_attempted_at=_NOW,
        updated_at=_NOW,
    )


def _beatmap_domain(
    *,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    local_status_override: LocalBeatmapStatus | None = None,
    local_status_override_changed_at: datetime | None = None,
    official_last_updated_at: datetime | None = None,
) -> Beatmap:
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
        official_last_updated_at=official_last_updated_at,
        local_status_override_changed_at=local_status_override_changed_at,
    )


def _beatmapset_domain(beatmap: Beatmap) -> BeatmapSet:
    return BeatmapSet(
        id=1_000,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _attachment_domain() -> BeatmapFileAttachment:
    return BeatmapFileAttachment(
        beatmap_id=2_000,
        blob_id=55,
        checksum_md5=_CHECKSUM,
        source=BeatmapFileSource.OFFICIAL,
        original_filename="2000.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
        id=1,
    )


def test_sqlalchemy_beatmap_repository_satisfies_contract() -> None:
    assert isinstance(_repo(FakeSession()), BeatmapCommandRepository)


async def test_get_beatmap_maps_model_and_current_attachment_to_domain() -> None:
    session = FakeSession(
        get_results={(BeatmapModel, 2_000): _beatmap_model()},
        execute_results=[FakeResult(_attachment_model())],
    )

    result = await _repo(session).get_beatmap(2_000)

    assert result is not None
    assert result.id == 2_000
    assert result.file_state is BeatmapFileState.AVAILABLE
    assert result.file_attachment == _attachment_domain()


async def test_get_beatmapset_loads_child_beatmaps() -> None:
    session = FakeSession(
        get_results={(BeatmapSetModel, 1_000): _beatmapset_model()},
        execute_results=[FakeResult(values=[_beatmap_model()]), FakeResult()],
    )

    result = await _repo(session).get_beatmapset(1_000)

    assert result is not None
    assert result.id == 1_000
    assert len(result.beatmaps) == 1
    assert result.beatmaps[0].checksum_md5 == _CHECKSUM


async def test_save_snapshot_preserves_existing_local_override() -> None:
    override_changed_at = datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC)
    existing = _beatmap_model(
        local_status_override="ranked",
        local_status_override_changed_at=override_changed_at,
    )
    session = FakeSession(get_results={(BeatmapModel, 2_000): existing})

    await _repo(session).save_beatmapset_snapshot(
        _beatmapset_domain(_beatmap_domain(official_status=BeatmapRankStatus.LOVED))
    )

    assert session.flushes == 1
    beatmap_models = [model for model in session.merged if isinstance(model, BeatmapModel)]
    assert len(beatmap_models) == 1
    assert beatmap_models[0].official_status == "loved"
    assert beatmap_models[0].local_status_override == "ranked"
    assert beatmap_models[0].local_status_override_changed_at == override_changed_at


async def test_save_snapshot_preserves_existing_last_updated_when_source_omits_it() -> None:
    official_last_updated_at = datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC)
    existing = _beatmap_model(official_last_updated_at=official_last_updated_at)
    session = FakeSession(get_results={(BeatmapModel, 2_000): existing})

    await _repo(session).save_beatmapset_snapshot(_beatmapset_domain(_beatmap_domain()))

    beatmap_models = [model for model in session.merged if isinstance(model, BeatmapModel)]
    assert len(beatmap_models) == 1
    assert beatmap_models[0].official_last_updated_at == official_last_updated_at


async def test_save_snapshot_preserves_existing_submission_counts() -> None:
    existing = _beatmap_model(play_count=9, pass_count=7)
    session = FakeSession(get_results={(BeatmapModel, 2_000): existing})

    await _repo(session).save_beatmapset_snapshot(_beatmapset_domain(_beatmap_domain()))

    beatmap_models = [model for model in session.merged if isinstance(model, BeatmapModel)]
    assert len(beatmap_models) == 1
    assert beatmap_models[0].play_count == 9
    assert beatmap_models[0].pass_count == 7


async def test_save_snapshot_rejects_existing_checksum_conflict_before_flush() -> None:
    conflicting_model = _beatmap_model(id=999, checksum_md5=_CHECKSUM)
    session = FakeSession(
        execute_results=[FakeResult(conflicting_model)],
    )

    with pytest.raises(DuplicateBeatmapChecksumError) as exc_info:
        await _repo(session).save_beatmapset_snapshot(_beatmapset_domain(_beatmap_domain()))

    assert exc_info.value.checksum_md5 == _CHECKSUM
    assert exc_info.value.existing_beatmap_id == 999
    assert session.flushes == 0


async def test_attach_osu_file_returns_existing_duplicate_attachment() -> None:
    session = FakeSession(
        get_results={(BeatmapModel, 2_000): _beatmap_model()},
        execute_results=[FakeResult(_attachment_model())],
    )

    result = await _repo(session).attach_osu_file(_attachment_domain())

    assert result == _attachment_domain()
    assert session.added == []
    assert session.flushes == 0


async def test_fetch_pending_marker_is_idempotent_until_completed() -> None:
    target = BeatmapFetchTarget.metadata_by_beatmap_id(2_000)
    pending_session = FakeSession(execute_results=[FakeResult()])

    assert await _repo(pending_session).try_mark_fetch_pending(target, now=_NOW) is False
    assert pending_session.flushes == 0

    retry_session = FakeSession(execute_results=[FakeResult(1)])

    assert await _repo(retry_session).try_mark_fetch_pending(target, now=_NOW) is True
    assert retry_session.flushes == 0


async def test_fetch_pending_marker_uses_atomic_conflict_update() -> None:
    target = BeatmapFetchTarget.metadata_by_checksum(_CHECKSUM)
    session = FakeSession(execute_results=[FakeResult(1)])

    assert await _repo(session).try_mark_fetch_pending(target, now=_NOW) is True

    assert len(session.executed) == 1
    statement = session.executed[0]
    assert isinstance(statement, ClauseElement)
    statement_text = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in statement_text
    assert "DO UPDATE" in statement_text
    assert "WHERE beatmap_fetch_states.status != " in statement_text
    assert "RETURNING beatmap_fetch_states.id" in statement_text
    assert session.added == []
    assert session.flushes == 0


async def test_fetch_pending_marker_refreshes_identity_map_after_upsert() -> None:
    target = BeatmapFetchTarget.metadata_by_checksum(_CHECKSUM)
    session = FakeSession(
        get_results={(BeatmapFetchStateModel, 1): _fetch_state_model()},
        execute_results=[FakeResult(1)],
    )

    assert await _repo(session).try_mark_fetch_pending(target, now=_NOW) is True

    assert session.get_calls == [(BeatmapFetchStateModel, 1, True)]


async def test_get_beatmap_by_checksum_resolves_model_and_attachment() -> None:
    session = FakeSession(
        execute_results=[
            FakeResult(_beatmap_model()),
            FakeResult(_attachment_model()),
        ],
    )

    result = await _repo(session).get_beatmap_by_checksum(_CHECKSUM)

    assert result is not None
    assert result.id == 2_000
    assert result.checksum_md5 == _CHECKSUM
    assert result.file_state is BeatmapFileState.AVAILABLE
    assert result.file_attachment == _attachment_domain()


async def test_get_beatmap_by_checksum_returns_none_when_not_found() -> None:
    session = FakeSession(execute_results=[FakeResult()])

    result = await _repo(session).get_beatmap_by_checksum("nonexistentchecksum00000000000000")

    assert result is None


async def test_set_local_status_override_updates_model_and_returns_domain() -> None:
    model = _beatmap_model(official_status="pending", local_status_override=None)
    session = FakeSession(
        get_results={(BeatmapModel, 2_000): model},
        execute_results=[FakeResult()],
    )

    result = await _repo(session).set_local_status_override(2_000, LocalBeatmapStatus.RANKED)

    assert model.local_status_override == "ranked"
    assert model.local_status_override_changed_at is not None
    assert result.local_status_override is LocalBeatmapStatus.RANKED
    assert result.local_status_override_changed_at == model.local_status_override_changed_at
    assert result.official_status is BeatmapRankStatus.PENDING
    assert session.flushes == 1


async def test_set_local_status_override_clears_override_with_none() -> None:
    model = _beatmap_model(local_status_override="ranked")
    session = FakeSession(
        get_results={(BeatmapModel, 2_000): model},
        execute_results=[FakeResult()],
    )

    result = await _repo(session).set_local_status_override(2_000, None)

    assert model.local_status_override is None
    assert model.local_status_override_changed_at is None
    assert result.local_status_override is None
    assert result.local_status_override_changed_at is None
    assert session.flushes == 1


async def test_set_local_status_override_raises_not_found() -> None:
    session = FakeSession()

    with pytest.raises(BeatmapNotFoundError):
        _ = await _repo(session).set_local_status_override(9_999, LocalBeatmapStatus.RANKED)


async def test_increment_submission_counts_uses_atomic_update_returning() -> None:
    session = FakeSession(execute_results=[FakeResult(row=(3, 2))])

    result = await _repo(session).increment_submission_counts(2_000, passed=True)

    assert result.play_count == 3
    assert result.pass_count == 2
    assert len(session.executed) == 1
    statement = session.executed[0]
    assert isinstance(statement, ClauseElement)
    statement_text = str(statement.compile(dialect=postgresql.dialect()))
    assert "UPDATE beatmaps SET" in statement_text
    assert "play_count=(beatmaps.play_count + " in statement_text
    assert "pass_count=(beatmaps.pass_count + " in statement_text
    assert "WHERE beatmaps.id = " in statement_text
    assert "RETURNING beatmaps.play_count, beatmaps.pass_count" in statement_text


async def test_increment_submission_counts_raises_when_beatmap_missing() -> None:
    session = FakeSession(execute_results=[FakeResult(row=None)])

    with pytest.raises(BeatmapNotFoundError):
        _ = await _repo(session).increment_submission_counts(9_999, passed=False)


async def test_mark_fetch_succeeded_transitions_state_to_fresh() -> None:
    target = BeatmapFetchTarget.metadata_by_beatmap_id(2_000)
    model = _fetch_state_model(status="pending_fetch")
    session = FakeSession(execute_results=[FakeResult(model)])

    await _repo(session).mark_fetch_succeeded(target, now=_NOW)

    assert model.status == "fresh"
    assert model.last_error is None
    assert model.pending_since is None
    assert model.last_attempted_at == _NOW
    assert session.flushes == 1


async def test_mark_fetch_failed_records_error_and_transitions_state() -> None:
    target = BeatmapFetchTarget.file_by_beatmap_id(2_000)
    model = _fetch_state_model(status="pending_fetch")
    session = FakeSession(execute_results=[FakeResult(model)])

    await _repo(session).mark_fetch_failed(target, reason="timeout", now=_NOW)

    assert model.status == "failed"
    assert model.last_error == "timeout"
    assert model.pending_since is None
    assert model.last_attempted_at == _NOW
    assert session.flushes == 1


async def test_attach_osu_file_inserts_new_attachment() -> None:
    session = FakeSession(
        get_results={(BeatmapModel, 2_000): _beatmap_model()},
        execute_results=[FakeResult()],
    )

    result = await _repo(session).attach_osu_file(_attachment_domain())

    assert result == _attachment_domain()
    assert len(session.added) == 1
    assert isinstance(session.added[0], BeatmapFileAttachmentModel)
    assert session.added[0].beatmap_id == 2_000
    assert session.added[0].checksum_md5 == _CHECKSUM
    assert session.flushes == 1
    assert len(session.refreshed) == 1


async def test_save_new_beatmapset_snapshot_merges_set_and_beatmaps() -> None:
    session = FakeSession()

    await _repo(session).save_beatmapset_snapshot(_beatmapset_domain(_beatmap_domain()))

    set_models = [m for m in session.merged if isinstance(m, BeatmapSetModel)]
    beatmap_models = [m for m in session.merged if isinstance(m, BeatmapModel)]
    assert len(set_models) == 1
    assert set_models[0].id == 1_000
    assert len(beatmap_models) == 1
    assert beatmap_models[0].id == 2_000
    assert session.flushes == 1
