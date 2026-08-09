"""osu!direct indexing command use-caseの契約を検証するmodule."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSetSearchDocument,
    BeatmapSourceVerification,
    DirectExternalIndexBackend,
    DirectExternalIndexStatus,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.beatmaps.direct_indexing import (
    DirectExternalIndexUpdateOutcome,
    DirectIndexingCommands,
)

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)


@dataclass(slots=True)
class RecordingExternalIndexBackend:
    """External index backendのdocument更新を記録するtest double.

    Attributes:
        failing_beatmapset_ids (set[int]): 失敗させるbeatmapset ID集合.
        indexed_documents (list[BeatmapSetSearchDocument]): 更新要求されたdocument列.
    """

    failing_beatmapset_ids: set[int] = field(default_factory=set)
    indexed_documents: list[BeatmapSetSearchDocument] = field(default_factory=list)

    async def index_document(self, document: BeatmapSetSearchDocument) -> None:
        """Document更新要求を記録し,指定IDでは失敗する.

        Args:
            document (BeatmapSetSearchDocument): external indexへ送るprojection document.

        Returns:
            None: 更新要求を記録して完了する.

        Raises:
            RuntimeError: documentのbeatmapset IDが失敗対象の場合.
        """
        if document.beatmapset_id in self.failing_beatmapset_ids:
            msg = "raw upstream secret-token stacktrace"
            raise RuntimeError(msg)
        self.indexed_documents.append(document)


async def test_rebuild_search_projection_restores_missing_projection_from_metadata() -> None:
    """保存済みmetadataから削除済み検索projectionを復元できることを検証する.

    Returns:
        None: rebuild結果と復元documentのidempotentなversionを検証して完了する.
    """
    state = InMemoryCommandRepositoryState()
    factory = InMemoryUnitOfWorkFactory(state)
    await _save_beatmapset(factory, _make_beatmapset(beatmapset_id=1_000))
    state.search_documents_by_beatmapset_id.clear()
    commands = DirectIndexingCommands(unit_of_work_factory=factory)

    result = await commands.rebuild_search_projection()

    document = factory.snapshot().search_documents_by_beatmapset_id[1_000]
    assert result.rebuilt_count == 1
    assert document.beatmapset_id == 1_000
    assert document.is_active is True
    first_version = document.document_version

    second_result = await commands.rebuild_search_projection()

    assert second_result.rebuilt_count == 1
    assert factory.snapshot().search_documents_by_beatmapset_id[1_000].document_version == (
        first_version
    )


async def test_update_external_index_records_success_after_committed_projection_read() -> None:
    """Committed projectionをexternal indexへ送り成功stateを記録することを検証する.

    Returns:
        None: external backend呼出と成功index stateを検証して完了する.
    """
    state = InMemoryCommandRepositoryState()
    factory = InMemoryUnitOfWorkFactory(state)
    await _save_beatmapset(factory, _make_beatmapset(beatmapset_id=1_000))
    external_index = RecordingExternalIndexBackend()
    commands = DirectIndexingCommands(
        unit_of_work_factory=factory,
        external_index_backend=external_index,
    )

    result = await commands.update_external_index(1_000)

    snapshot = factory.snapshot()
    index_state = snapshot.external_index_states_by_key[
        (DirectExternalIndexBackend.MEILISEARCH, 1_000)
    ]
    assert result.outcome is DirectExternalIndexUpdateOutcome.SUCCEEDED
    assert external_index.indexed_documents[0].beatmapset_id == 1_000
    assert index_state.status is DirectExternalIndexStatus.SUCCEEDED
    assert index_state.document_version == external_index.indexed_documents[0].document_version
    assert index_state.failure_reason is None


async def test_update_external_index_failure_records_retry_state_without_projection_loss() -> None:
    """External index失敗時もSQL projectionを残して失敗stateを記録する.

    Returns:
        None: 失敗state, sanitized reason, projection維持を検証して完了する.
    """
    state = InMemoryCommandRepositoryState()
    factory = InMemoryUnitOfWorkFactory(state)
    await _save_beatmapset(factory, _make_beatmapset(beatmapset_id=1_000))
    external_index = RecordingExternalIndexBackend(failing_beatmapset_ids={1_000})
    commands = DirectIndexingCommands(
        unit_of_work_factory=factory,
        external_index_backend=external_index,
    )

    result = await commands.update_external_index(1_000)

    snapshot = factory.snapshot()
    index_state = snapshot.external_index_states_by_key[
        (DirectExternalIndexBackend.MEILISEARCH, 1_000)
    ]
    assert result.outcome is DirectExternalIndexUpdateOutcome.FAILED
    assert snapshot.search_documents_by_beatmapset_id[1_000].is_active is True
    assert index_state.status is DirectExternalIndexStatus.FAILED
    assert index_state.failure_reason is not None
    assert "secret-token" not in index_state.failure_reason
    assert "stacktrace" not in index_state.failure_reason


async def test_rebuild_external_index_replays_current_projection_documents() -> None:
    """Current projection群からexternal index stateを再構築することを検証する.

    Returns:
        None: 成功と失敗を混在させても各projectionのstateが記録されることを確認する.
    """
    state = InMemoryCommandRepositoryState()
    factory = InMemoryUnitOfWorkFactory(state)
    await _save_beatmapset(factory, _make_beatmapset(beatmapset_id=1_000))
    await _save_beatmapset(factory, _make_beatmapset(beatmapset_id=2_000))
    external_index = RecordingExternalIndexBackend(failing_beatmapset_ids={2_000})
    commands = DirectIndexingCommands(
        unit_of_work_factory=factory,
        external_index_backend=external_index,
    )

    result = await commands.rebuild_external_index()

    snapshot = factory.snapshot()
    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert [document.beatmapset_id for document in external_index.indexed_documents] == [1_000]
    assert (
        snapshot.external_index_states_by_key[
            (DirectExternalIndexBackend.MEILISEARCH, 1_000)
        ].status
        is DirectExternalIndexStatus.SUCCEEDED
    )
    assert (
        snapshot.external_index_states_by_key[
            (DirectExternalIndexBackend.MEILISEARCH, 2_000)
        ].status
        is DirectExternalIndexStatus.FAILED
    )


async def _save_beatmapset(
    factory: InMemoryUnitOfWorkFactory,
    beatmapset: BeatmapSet,
) -> None:
    """In-memory UoWへbeatmapset snapshotを保存してcommitする.

    Args:
        factory (InMemoryUnitOfWorkFactory): 保存先のcommand UoW factory.
        beatmapset (BeatmapSet): 保存するbeatmapset metadata.

    Returns:
        None: metadataとprojectionをcommitして完了する.
    """
    async with factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(beatmapset)
        await uow.commit()


def _make_beatmapset(*, beatmapset_id: int) -> BeatmapSet:
    """Direct indexing command test用のbeatmapset metadataを作成する.

    Args:
        beatmapset_id (int): 作成するbeatmapset ID.

    Returns:
        BeatmapSet: 1 child beatmapを持つranked beatmapset.
    """
    beatmap = _make_beatmap(
        beatmap_id=beatmapset_id + 1_000,
        beatmapset_id=beatmapset_id,
    )
    return BeatmapSet(
        id=beatmapset_id,
        artist=f"Artist {beatmapset_id}",
        title=f"Title {beatmapset_id}",
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


def _make_beatmap(*, beatmap_id: int, beatmapset_id: int) -> Beatmap:
    """Direct indexing command test用のchild beatmap metadataを作成する.

    Args:
        beatmap_id (int): 作成するbeatmap ID.
        beatmapset_id (int): 所属するbeatmapset ID.

    Returns:
        Beatmap: projectionへ使えるranked child beatmap.
    """
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=f"{beatmap_id:032x}",
        mode=BeatmapMode.OSU,
        version=f"Difficulty {beatmap_id}",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
        official_last_updated_at=_NOW,
    )
