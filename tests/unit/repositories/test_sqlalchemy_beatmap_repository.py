"""SQLAlchemy beatmap command repositoryの永続化契約を検証するunit test.

Modelとdomain値の変換, snapshot保存, fetch状態遷移, file attachmentの扱いを
in-memory session fakeで確認する.
"""

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
    BeatmapFetchTargetKind,
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
    """SQLAlchemy execute結果で使う最小のResult fake.

    Attributes:
        _value (object | None): scalar_one_or_none()が返す値.
        _values (list[object]): scalars().all()が返す値列.
        _row (tuple[object, object] | None): one_or_none()が返すrow.
    """

    _value: object | None
    _values: list[object]
    _row: tuple[object, object] | None

    def __init__(
        self,
        value: object | None = None,
        values: list[object] | None = None,
        row: tuple[object, object] | None = None,
    ) -> None:
        """Scalar値, 値列, またはrowを返すResult fakeを初期化する.

        Args:
            value (object | None): scalar_one_or_none()で返す値. 未指定時はNone.
            values (list[object] | None): all()で返す値列. 未指定時は空列.
            row (tuple[object, object] | None): one_or_none()で返すrow. 未指定時はNone.

        Returns:
            None: Result fakeの固定応答を設定して値を返さない.
        """
        self._value = value
        self._values = values or []
        self._row = row

    def scalar_one_or_none(self) -> object | None:
        """設定済みのscalar値を返す.

        Returns:
            object | None: scalar query結果. 値がない場合はNone.
        """
        return self._value

    def one_or_none(self) -> tuple[object, object] | None:
        """設定済みの単一rowを返す.

        Returns:
            tuple[object, object] | None: query結果のrow. rowがない場合はNone.
        """
        return self._row

    def scalars(self) -> FakeResult:
        """値列を返すscalar resultとして自身を返す.

        Returns:
            FakeResult: all()を続けて呼べる自身.
        """
        return self

    def all(self) -> list[object]:
        """設定済みの値列を返す.

        Returns:
            list[object]: scalar query結果として設定した値列.
        """
        return self._values


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    """SQLAlchemy AsyncSessionのrepository利用分を記録するfake.

    Attributes:
        get_results (dict[tuple[type[object], int], object]): get()呼び出しに対応する値.
        execute_results (list[FakeResult]): execute()呼び出し順に返すResult fake列.
        flush_error (IntegrityError | None): flush()時に送出する任意の整合性error.
        added (list[object]): add()へ渡されたmodel列.
        merged (list[object]): merge()へ渡されたmodel列.
        refreshed (list[object]): refresh()したmodel列.
        executed (list[Executable]): execute()へ渡されたSQLAlchemy statement列.
        get_calls (list[tuple[type[object], int, bool]]): get()のmodel, identity, refresh指定.
        flushes (int): 成功したflush()の呼び出し回数.
    """

    def __init__(
        self,
        *,
        get_results: dict[tuple[type[object], int], object] | None = None,
        execute_results: list[FakeResult] | None = None,
        flush_error: IntegrityError | None = None,
    ) -> None:
        """Repository assertionに必要なsession応答と記録列を初期化する.

        Args:
            get_results (dict[tuple[type[object], int], object] | None): get()の固定結果.
                未指定時は空の対応表を使う.
            execute_results (list[FakeResult] | None): execute()が順に返す結果列.
                未指定時は空列を使う.
            flush_error (IntegrityError | None): flush()で送出するerror. 未指定時は送出しない.

        Returns:
            None: fake sessionの応答と呼び出し記録を設定して値を返さない.
        """
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
        """Async context内で使用する自身を返す.

        Returns:
            FakeSession: repositoryが使用する同一session fake.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Async context終了時に例外情報を消費する.

        Args:
            exc_type (type[BaseException] | None): 発生した例外の型. 例外がない場合はNone.
            exc (BaseException | None): 発生した例外. 例外がない場合はNone.
            traceback (TracebackType | None): 発生箇所のtraceback. 例外がない場合はNone.

        Returns:
            None: rollback等を行わず例外情報だけを破棄する.
        """
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
        """Model型とidentityに対応する固定結果を取得する.

        Args:
            model_type (type[object]): 取得対象のSQLAlchemy model型.
            identity (int): 取得対象の永続化識別子.
            populate_existing (bool): identity mapを再読込するか. 既定値はFalse.

        Returns:
            object | None: 対応表に設定されたmodel. 未設定時はNone.
        """
        self.get_calls.append((model_type, identity, populate_existing))
        return self.get_results.get((model_type, identity))

    async def execute(self, statement: Executable) -> FakeResult:
        """SQLAlchemy statementを記録して次の固定結果を返す.

        Args:
            statement (Executable): repositoryが実行するSQLAlchemy statement.

        Returns:
            FakeResult: 設定済み結果列の先頭. 結果がなければ空のResult fake.
        """
        self.executed.append(statement)
        if not self.execute_results:
            return FakeResult()
        return self.execute_results.pop(0)

    async def merge(self, instance: object) -> object:
        """Merge対象modelを記録して同じinstanceを返す.

        Args:
            instance (object): mergeするSQLAlchemy model相当の値.

        Returns:
            object: 記録した入力instance.
        """
        self.merged.append(instance)
        return instance

    def add(self, instance: object) -> None:
        """追加対象modelを記録する.

        Args:
            instance (object): sessionへ追加するSQLAlchemy model相当の値.

        Returns:
            None: 追加対象を記録して値を返さない.
        """
        self.added.append(instance)

    async def flush(self) -> None:
        """設定済みerrorを送出するか成功回数を記録する.

        Returns:
            None: 成功時にflush回数を増やして値を返さない.

        Raises:
            IntegrityError: flush_errorが設定されている場合.
        """
        if self.flush_error is not None:
            raise self.flush_error
        self.flushes += 1

    async def refresh(self, instance: object) -> None:
        """新規attachmentまたはfetch stateへ永続化済み属性を設定する.

        Args:
            instance (object): refreshするSQLAlchemy model相当の値.

        Returns:
            None: 対応modelの識別子と時刻を設定して記録する.
        """
        if isinstance(instance, BeatmapFileAttachmentModel):
            instance.id = 1
            instance.created_at = _NOW
        if isinstance(instance, BeatmapFetchStateModel):
            instance.id = 1
            instance.updated_at = _NOW
        self.refreshed.append(instance)


def _repo(session: FakeSession) -> SQLAlchemyBeatmapCommandRepository:
    """FakeSessionを使うSQLAlchemy beatmap command repositoryを構築する.

    Args:
        session (FakeSession): AsyncSessionとして扱うrepository用session fake.

    Returns:
        SQLAlchemyBeatmapCommandRepository: assertion対象のrepository.
    """
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
    """指定属性を持つ永続化済みbeatmap modelを作成する.

    Args:
        id (int): beatmap永続化識別子.
        checksum_md5 (str): beatmapのMD5 checksum.
        official_status (str): upstreamから取得したrank status値.
        local_status_override (str | None): 管理者によるlocal status上書き. 未設定時はNone.
        local_status_override_changed_at (datetime | None): local上書きの更新時刻. 未設定時はNone.
        official_last_updated_at (datetime | None): upstream metadata更新時刻. 未設定時はNone.
        play_count (int): 保存済みplay count.
        pass_count (int): 保存済みpass count.

    Returns:
        BeatmapModel: repositoryの変換と保存を検証するmodel.
    """
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
    """固定metadataを持つ永続化済みbeatmapset modelを作成する.

    Returns:
        BeatmapSetModel: beatmapset取得とsnapshot保存に使うmodel.
    """
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
    """利用可能なosu file attachment modelを作成する.

    Returns:
        BeatmapFileAttachmentModel: checksum検証済みblob attachmentを表すmodel.
    """
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
    """指定状態を持つbeatmap metadata fetch state modelを作成する.

    Args:
        status (str): fetch lifecycleとして保存する状態値. 既定値はpending_fetch.

    Returns:
        BeatmapFetchStateModel: metadata fetchの時刻とattempt countを持つmodel.
    """
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
    """Repository入力として使うranked beatmap domain値を作成する.

    Args:
        official_status (BeatmapRankStatus): upstreamが示すrank status.
        local_status_override (LocalBeatmapStatus | None): 管理者によるlocal status上書き.
        local_status_override_changed_at (datetime | None): local上書きの更新時刻.
        official_last_updated_at (datetime | None): upstream metadataの更新時刻.

    Returns:
        Beatmap: snapshot保存とstatus更新を検証するdomain beatmap.
    """
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
    """指定beatmapを含むdomain beatmapsetを作成する.

    Args:
        beatmap (Beatmap): beatmapsetへ含めるdomain beatmap.

    Returns:
        BeatmapSet: snapshot保存に使用する1件のbeatmapを持つbeatmapset.
    """
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
    """Blobに紐付くdomain osu file attachmentを作成する.

    Returns:
        BeatmapFileAttachment: attachment保存と取得を検証するdomain値.
    """
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
    """Repository実装がBeatmapCommandRepository contractを満たすことを検証する.

    Returns:
        None: interface実装のisinstance assertionを行って値を返さない.

    Raises:
        AssertionError: repositoryがcommand repository contractを実装しない場合.
    """
    assert isinstance(_repo(FakeSession()), BeatmapCommandRepository)


async def test_get_beatmap_maps_model_and_current_attachment_to_domain() -> None:
    """Beatmap modelとcurrent attachmentがdomain値へ変換されることを検証する.

    Returns:
        None: beatmap識別子, file状態, attachmentのassertionを行って値を返さない.

    Raises:
        AssertionError: modelまたはattachmentのdomain変換結果が期待と異なる場合.
    """
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
    """Beatmapset取得がchild beatmapを含むdomain値を返すことを検証する.

    Returns:
        None: beatmapset識別子とchild checksumのassertionを行って値を返さない.

    Raises:
        AssertionError: beatmapsetまたはchild beatmapの変換結果が期待と異なる場合.
    """
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
    """Snapshot保存が既存local status overrideを保持することを検証する.

    Returns:
        None: merged modelのofficial statusとlocal overrideをassertして値を返さない.

    Raises:
        AssertionError: local overrideまたは更新時刻が上書きされる場合.
    """
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
    """Snapshot sourceが時刻を省略した場合に既存upstream更新時刻を保持することを検証する.

    Returns:
        None: merged modelのofficial_last_updated_atをassertして値を返さない.

    Raises:
        AssertionError: source未指定時に既存更新時刻が失われる場合.
    """
    official_last_updated_at = datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC)
    existing = _beatmap_model(official_last_updated_at=official_last_updated_at)
    session = FakeSession(get_results={(BeatmapModel, 2_000): existing})

    await _repo(session).save_beatmapset_snapshot(_beatmapset_domain(_beatmap_domain()))

    beatmap_models = [model for model in session.merged if isinstance(model, BeatmapModel)]
    assert len(beatmap_models) == 1
    assert beatmap_models[0].official_last_updated_at == official_last_updated_at


async def test_save_snapshot_preserves_existing_submission_counts() -> None:
    """Snapshot保存が既存play countとpass countを保持することを検証する.

    Returns:
        None: merged modelのsubmission countをassertして値を返さない.

    Raises:
        AssertionError: snapshot保存で既存submission countが上書きされる場合.
    """
    existing = _beatmap_model(play_count=9, pass_count=7)
    session = FakeSession(get_results={(BeatmapModel, 2_000): existing})

    await _repo(session).save_beatmapset_snapshot(_beatmapset_domain(_beatmap_domain()))

    beatmap_models = [model for model in session.merged if isinstance(model, BeatmapModel)]
    assert len(beatmap_models) == 1
    assert beatmap_models[0].play_count == 9
    assert beatmap_models[0].pass_count == 7


async def test_save_snapshot_rejects_existing_checksum_conflict_before_flush() -> None:
    """異なるbeatmap識別子のchecksum競合をflush前に拒否することを検証する.

    Returns:
        None: DuplicateBeatmapChecksumErrorの値とflush未実行をassertして値を返さない.

    Raises:
        AssertionError: 競合errorの内容またはflush回数が期待と異なる場合.
    """
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
    """同一attachmentの保存要求が既存domain attachmentを返すことを検証する.

    Returns:
        None: attachment再利用と新規addおよびflush未実行をassertして値を返さない.

    Raises:
        AssertionError: duplicate attachmentで新規永続化が行われる場合.
    """
    session = FakeSession(
        get_results={(BeatmapModel, 2_000): _beatmap_model()},
        execute_results=[FakeResult(_attachment_model())],
    )

    result = await _repo(session).attach_osu_file(_attachment_domain())

    assert result == _attachment_domain()
    assert session.added == []
    assert session.flushes == 0


async def test_fetch_pending_marker_is_idempotent_until_completed() -> None:
    """Pending fetch markerが完了前はidempotentに拒否または再取得されることを検証する.

    Returns:
        None: pending状態のFalseと再試行時のTrueをassertして値を返さない.

    Raises:
        AssertionError: pending markerの再試行可能性またはflush回数が期待と異なる場合.
    """
    target = BeatmapFetchTarget.metadata_by_beatmap_id(2_000)
    pending_session = FakeSession(execute_results=[FakeResult()])

    assert await _repo(pending_session).try_mark_fetch_pending(target, now=_NOW) is False
    assert pending_session.flushes == 0

    retry_session = FakeSession(execute_results=[FakeResult(1)])

    assert await _repo(retry_session).try_mark_fetch_pending(target, now=_NOW) is True
    assert retry_session.flushes == 0


async def test_string_fetch_target_kind_is_normalized_for_query_and_write() -> None:
    """Runtime string target_typeをqueryとwriteの両方でtyped kindへ正規化する.

    Returns:
        None: lookup, pending upsert, completed insertが正規化値を使用したことを示す.

    Raises:
        AssertionError: string target_typeでAttributeErrorまたは誤った保存値が生じる場合.
    """
    target = BeatmapFetchTarget(
        target_type=cast("BeatmapFetchTargetKind", cast("object", "metadata:beatmap")),
        target_key="2000",
    )
    lookup_session = FakeSession(execute_results=[FakeResult(_fetch_state_model())])

    assert await _repo(lookup_session).get_fetch_state(target) is not None

    pending_session = FakeSession(execute_results=[FakeResult(1)])
    assert await _repo(pending_session).try_mark_fetch_pending(target, now=_NOW) is True

    completed_session = FakeSession(execute_results=[FakeResult()])
    await _repo(completed_session).mark_fetch_succeeded(target, now=_NOW)
    created = completed_session.added[0]
    assert isinstance(created, BeatmapFetchStateModel)
    assert created.target_type == BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID.value


async def test_fetch_pending_marker_uses_atomic_conflict_update() -> None:
    """Pending fetch markerがatomic upsertとRETURNINGを使うことを検証する.

    Returns:
        None: PostgreSQL statementのON CONFLICTと更新条件をassertして値を返さない.

    Raises:
        AssertionError: upsert statementまたはsession副作用が期待と異なる場合.
    """
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
    """Pending fetch upsert後にidentity mapを再読込することを検証する.

    Returns:
        None: populate_existingを指定したget()呼び出しをassertして値を返さない.

    Raises:
        AssertionError: upsert後のfetch stateがidentity mapから再読込されない場合.
    """
    target = BeatmapFetchTarget.metadata_by_checksum(_CHECKSUM)
    session = FakeSession(
        get_results={(BeatmapFetchStateModel, 1): _fetch_state_model()},
        execute_results=[FakeResult(1)],
    )

    assert await _repo(session).try_mark_fetch_pending(target, now=_NOW) is True

    assert session.get_calls == [(BeatmapFetchStateModel, 1, True)]


async def test_get_beatmap_by_checksum_resolves_model_and_attachment() -> None:
    """Checksum検索がbeatmap modelとattachmentをdomain値へ変換することを検証する.

    Returns:
        None: beatmap識別子, checksum, file状態, attachmentをassertして値を返さない.

    Raises:
        AssertionError: checksum検索のdomain変換結果が期待と異なる場合.
    """
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
    """存在しないchecksum検索がNoneを返すことを検証する.

    Returns:
        None: query結果がNoneであることをassertして値を返さない.

    Raises:
        AssertionError: 未登録checksumにbeatmapが返される場合.
    """
    session = FakeSession(execute_results=[FakeResult()])

    result = await _repo(session).get_beatmap_by_checksum("nonexistentchecksum00000000000000")

    assert result is None


async def test_set_local_status_override_updates_model_and_returns_domain() -> None:
    """Local status override設定がmodelとdomain戻り値へ反映されることを検証する.

    Returns:
        None: override値, 更新時刻, official statusをassertして値を返さない.

    Raises:
        AssertionError: override設定後のmodelまたはdomain値が期待と異なる場合.
    """
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
    """None指定が既存local status overrideと更新時刻を消去することを検証する.

    Returns:
        None: modelとdomain戻り値のoverride関連属性をassertして値を返さない.

    Raises:
        AssertionError: None指定後にlocal overrideまたは更新時刻が残る場合.
    """
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
    """存在しないbeatmapへのlocal status override設定がerrorになることを検証する.

    Returns:
        None: BeatmapNotFoundErrorが送出されることをassertして値を返さない.

    Raises:
        AssertionError: 未登録beatmapの更新でBeatmapNotFoundErrorが送出されない場合.
    """
    session = FakeSession()

    with pytest.raises(BeatmapNotFoundError):
        _ = await _repo(session).set_local_status_override(9_999, LocalBeatmapStatus.RANKED)


async def test_increment_submission_counts_uses_atomic_update_returning() -> None:
    """Submission count増分がatomic updateとRETURNINGを使うことを検証する.

    Returns:
        None: 更新後countとPostgreSQL statementの構造をassertして値を返さない.

    Raises:
        AssertionError: count増分, SQL更新式, またはRETURNING句が期待と異なる場合.
    """
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
    """存在しないbeatmapのsubmission count増分がerrorになることを検証する.

    Returns:
        None: BeatmapNotFoundErrorが送出されることをassertして値を返さない.

    Raises:
        AssertionError: 未登録beatmapの増分でBeatmapNotFoundErrorが送出されない場合.
    """
    session = FakeSession(execute_results=[FakeResult(row=None)])

    with pytest.raises(BeatmapNotFoundError):
        _ = await _repo(session).increment_submission_counts(9_999, passed=False)


async def test_mark_fetch_succeeded_transitions_state_to_fresh() -> None:
    """Fetch成功がpending stateをfreshへ遷移させることを検証する.

    Returns:
        None: lifecycle状態, error, 時刻, flush回数をassertして値を返さない.

    Raises:
        AssertionError: fetch成功後のstate遷移または永続化が期待と異なる場合.
    """
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
    """Fetch失敗がerrorを記録してfailed stateへ遷移させることを検証する.

    Returns:
        None: lifecycle状態, error reason, 時刻, flush回数をassertして値を返さない.

    Raises:
        AssertionError: fetch失敗後のstate遷移またはerror記録が期待と異なる場合.
    """
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
    """新規osu file attachmentがadd, flush, refreshされることを検証する.

    Returns:
        None: domain戻り値と新規attachment modelの属性をassertして値を返さない.

    Raises:
        AssertionError: 新規attachmentの保存結果またはsession副作用が期待と異なる場合.
    """
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
    """新規beatmapset snapshotがsetとchild beatmapをmergeすることを検証する.

    Returns:
        None: merged set, child beatmap, flush回数をassertして値を返さない.

    Raises:
        AssertionError: snapshot保存でsetまたはchild beatmapがmergeされない場合.
    """
    session = FakeSession()

    await _repo(session).save_beatmapset_snapshot(_beatmapset_domain(_beatmap_domain()))

    set_models = [m for m in session.merged if isinstance(m, BeatmapSetModel)]
    beatmap_models = [m for m in session.merged if isinstance(m, BeatmapModel)]
    assert len(set_models) == 1
    assert set_models[0].id == 1_000
    assert len(beatmap_models) == 1
    assert beatmap_models[0].id == 2_000
    assert session.flushes == 1
