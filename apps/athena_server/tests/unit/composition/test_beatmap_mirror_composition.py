"""Beatmap mirror provider wiring の composition 契約を検証する."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest
from tests.factories.config import make_app_config
from tests.support.beatmaps import InMemoryBeatmapStore

from osu_server.composition.providers.beatmaps_app import (
    BeatmapAppProviderSet,
    enqueue_beatmap_fetch,
)
from osu_server.composition.providers.container import make_app_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileProvider,
    BeatmapFileState,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    DirectPointLookupRequest,
    DirectSearchBackendResult,
    DirectSearchCandidate,
    DirectSearchRequest,
    DirectSearchUpstreamResult,
)
from osu_server.infrastructure.beatmaps import BeatmapFileProviderService
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from taskiq import AsyncBroker

    from osu_server.services.queries.beatmaps.direct_search import (
        DirectPointLookupQuery,
        DirectSearchQuery,
    )


class _FakeTask:
    """Taskiq task への enqueue 引数を記録する fake task.

    Attributes:
        calls (list[tuple[str, str]]): target type と key の enqueue 記録.
        force_refresh_calls (list[bool]): force refresh 指定の enqueue 記録.
    """

    def __init__(self) -> None:
        """空の enqueue 記録を持つ fake task を初期化する."""
        self.calls: list[tuple[str, str]] = []
        self.force_refresh_calls: list[bool] = []

    async def kiq(
        self,
        target_type: str,
        target_key: str,
        *,
        force_refresh: bool = False,
    ) -> None:
        """Beatmap fetch job の enqueue 引数を記録する.

        Args:
            target_type (str): fetch 対象種別を表す queue 値.
            target_key (str): fetch 対象を識別する queue 値.
            force_refresh (bool): cache を使わず更新する指定か.

        Returns:
            None: enqueue 引数を記録し, 呼び出し側へ値を返さない.
        """
        self.calls.append((target_type, target_key))
        self.force_refresh_calls.append(force_refresh)


class _FakeBroker:
    """Metadata と file fetch task を名前で返す fake broker.

    Attributes:
        metadata (_FakeTask): metadata fetch task の記録先.
        direct_point_lookup_metadata (_FakeTask): point lookup専用metadata taskの記録先.
        file (_FakeTask): file fetch task の記録先.
    """

    def __init__(self) -> None:
        """三つの独立したfake taskを持つbrokerを初期化する."""
        self.metadata: _FakeTask = _FakeTask()
        self.direct_point_lookup_metadata: _FakeTask = _FakeTask()
        self.file: _FakeTask = _FakeTask()

    def find_task(self, task_name: str) -> _FakeTask | None:
        """既知の beatmap fetch task 名に対応する fake task を返す.

        Args:
            task_name (str): 検索する Taskiq task 名.

        Returns:
            _FakeTask | None: 対応する task. 未知の名前ではNone.
        """
        if task_name == "fetch_beatmap_metadata":
            return self.metadata
        if task_name == "fetch_osu_direct_point_lookup_metadata":
            return self.direct_point_lookup_metadata
        if task_name == "fetch_beatmap_file":
            return self.file
        return None


class _EmptyDirectSearchBackend:
    """Composition test用にlocal候補を返さないdirect search backendを提供する."""

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """検索requestに関係なく空のlocal候補を返す.

        Args:
            request (DirectSearchRequest): query use-caseから渡された検索条件.

        Returns:
            DirectSearchBackendResult: local候補なしの検索結果.
        """
        _ = request
        return DirectSearchBackendResult(candidates=(), has_more=False)

    async def validate(self) -> None:
        """Backend validationを何もせず通過させる.

        Returns:
            None: test backendが利用可能であることを示す.
        """


class _FixedDirectSearchBackend:
    """Composition test用に固定local候補を返すdirect search backendを提供する.

    Attributes:
        beatmapset_ids (tuple[int, ...]): search結果に含めるbeatmapset ID列.
    """

    beatmapset_ids: tuple[int, ...]

    def __init__(self, beatmapset_ids: tuple[int, ...]) -> None:
        """固定候補ID列を保持する.

        Args:
            beatmapset_ids (tuple[int, ...]): searchで返すbeatmapset ID列.
        """
        self.beatmapset_ids = beatmapset_ids

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """固定候補ID列をcandidate結果として返す.

        Args:
            request (DirectSearchRequest): query use-caseから渡された検索条件.

        Returns:
            DirectSearchBackendResult: 固定候補ID列を含む検索結果.
        """
        _ = request
        return DirectSearchBackendResult(
            candidates=tuple(
                DirectSearchCandidate(beatmapset_id=beatmapset_id, score=1.0)
                for beatmapset_id in self.beatmapset_ids
            ),
            has_more=False,
        )

    async def validate(self) -> None:
        """Backend validationを何もせず通過させる.

        Returns:
            None: test backendが利用可能であることを示す.
        """


class _FixedDirectSearchUpstreamProvider:
    """固定の外部検索結果を返すupstream provider test doubleを提供する.

    Attributes:
        result (DirectSearchUpstreamResult): searchで返す固定結果.
    """

    result: DirectSearchUpstreamResult

    def __init__(self, result: DirectSearchUpstreamResult) -> None:
        """返却する固定結果を保持する.

        Args:
            result (DirectSearchUpstreamResult): searchで返す結果.
        """
        self.result = result

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """Requestに関係なく固定の外部検索結果を返す.

        Args:
            request (DirectSearchRequest): query use-caseから渡された検索条件.

        Returns:
            DirectSearchUpstreamResult: 初期化時に渡された固定結果.
        """
        _ = request
        return self.result


@pytest.mark.asyncio
async def test_beatmap_mirror_dependencies_resolve_from_app_container(
    tmp_path: Path,
) -> None:
    """App container が in-memory runtime override 下でbeatmap mirrorの全依存を解決する.

    依存解決の契約を検証する.

    Args:
        tmp_path (Path): test 用 blob storage root を作る一時 directory.

    Returns:
        None: 解決した repository, provider, service の型を検証して完了する.
    """
    config = make_app_config(
        environment="test",
        blob_storage_local_root=str(tmp_path / "blobs"),
    )
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    try:
        assert isinstance(
            await container.get(BeatmapQueryRepository),
            InMemoryBeatmapQueryRepository,
        )
        assert isinstance(await container.get(BeatmapMirrorService), BeatmapMirrorService)
        assert isinstance(await container.get(BeatmapMetadataProvider), BeatmapMetadataProvider)
        assert isinstance(await container.get(BeatmapFileProvider), BeatmapFileProviderService)
        assert isinstance(
            await container.get(BeatmapEligibilityService),
            BeatmapEligibilityService,
        )
        assert isinstance(await container.get(BeatmapFreshnessPolicy), BeatmapFreshnessPolicy)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_routes_metadata_targets_to_metadata_job() -> None:
    """Metadata target の enqueue が metadata job だけへ target type と key を渡す契約を検証する.

    Returns:
        None: metadata task の記録と file task が未使用なことを検証して完了する.
    """
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.metadata_by_checksum("0123456789abcdef0123456789abcdef"),
    )

    assert broker.metadata.calls == [
        ("metadata:checksum", "0123456789abcdef0123456789abcdef"),
    ]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_preserves_force_refresh_flag() -> None:
    """Force refresh付きmetadata targetのenqueueがflagをmetadata jobへ保持する.

    この契約を検証する.

    Returns:
        None: target 値, force refresh 記録, file task の未使用を検証して完了する.
    """
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.metadata_by_beatmap_id(1, force_refresh=True),
    )

    assert broker.metadata.calls == [("metadata:beatmap", "1")]
    assert broker.metadata.force_refresh_calls == [True]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_direct_point_lookup_query_uses_dedicated_metadata_task() -> None:
    """DirectPointLookupQueryが専用metadata taskへfetchをenqueueする.

    Returns:
        None: lookup miss時に共通metadata taskではなく専用taskが使われることを確認する.
    """
    repo = InMemoryBeatmapStore()
    broker = _FakeBroker()
    config = make_app_config(osu_direct_point_lookup_bounded_wait_seconds=0.01)
    provider = BeatmapAppProviderSet()
    build_query = cast(
        "Callable[..., DirectPointLookupQuery]",
        provider.direct_point_lookup_query,
    )
    query = build_query(
        repository=repo.query_repository,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=BeatmapFreshnessPolicy(
            ranked_refresh_interval=timedelta(days=30),
            pending_refresh_interval=timedelta(hours=1),
            graveyard_refresh_interval=timedelta(days=30),
            mirror_refresh_interval=timedelta(hours=1),
        ),
        broker=cast("AsyncBroker", cast("object", broker)),
        config=config,
    )

    result = await query.execute(
        DirectPointLookupRequest.beatmapset_id(
            authenticated_user_id=1,
            beatmapset_id=1000,
        )
    )

    assert result.beatmapset is None
    assert broker.metadata.calls == []
    assert broker.direct_point_lookup_metadata.calls == [("metadata:beatmapset", "1000")]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_direct_search_query_enqueues_force_refresh_for_external_results() -> None:
    """外部検索で返したbeatmapsetのmetadata fetchをforce refreshでenqueueする契約を検証する.

    Returns:
        None: external候補がresponseへ入り, metadata jobへforce_refresh付きで渡ることを検証する.
    """
    repo = InMemoryBeatmapStore()
    broker = _FakeBroker()
    config = make_app_config(osu_direct_upstream_search_wait_seconds=0.01)
    upstream = _FixedDirectSearchUpstreamProvider(
        DirectSearchUpstreamResult(beatmapsets=(_direct_beatmapset(1000),))
    )
    provider = BeatmapAppProviderSet()
    build_query = cast("Callable[..., DirectSearchQuery]", provider.direct_search_query)
    query = build_query(
        repository=repo.query_repository,
        backend=_EmptyDirectSearchBackend(),
        upstream_provider=upstream,
        broker=cast("AsyncBroker", cast("object", broker)),
        config=config,
    )

    result = await query.execute(
        DirectSearchRequest(authenticated_user_id=1, query_text="camellia", page_size=1)
    )

    assert [beatmapset.id for beatmapset in result.beatmapsets] == [1000]
    assert result.coverage_record is not None
    assert broker.metadata.calls == [("metadata:beatmapset", "1000")]
    assert broker.metadata.force_refresh_calls == [True]
    assert broker.file.calls == []


@pytest.mark.asyncio
async def test_direct_search_query_uses_repository_coverage_reader() -> None:
    """CompositionしたDirectSearchQueryがcoverage欠落時に外部検索を起動する契約を検証する.

    Full local pageでもcoverageがない場合にprovider候補が返り、metadata fetchがforce refreshで
    enqueueされることを確認する.

    Returns:
        None: provider wiringがcoverage readerを渡していることを検証して完了する.
    """
    repo = InMemoryBeatmapStore()
    await repo.save_beatmapset_snapshot(_direct_beatmapset(10))
    broker = _FakeBroker()
    config = make_app_config(osu_direct_upstream_search_wait_seconds=0.01)
    upstream = _FixedDirectSearchUpstreamProvider(
        DirectSearchUpstreamResult(beatmapsets=(_direct_beatmapset(1000),))
    )
    provider = BeatmapAppProviderSet()
    build_query = cast("Callable[..., DirectSearchQuery]", provider.direct_search_query)
    query = build_query(
        repository=repo.query_repository,
        backend=_FixedDirectSearchBackend((10,)),
        upstream_provider=upstream,
        broker=cast("AsyncBroker", cast("object", broker)),
        config=config,
    )

    result = await query.execute(
        DirectSearchRequest(
            authenticated_user_id=1,
            query_text="camellia",
            page=1,
            page_size=1,
        )
    )

    assert [beatmapset.id for beatmapset in result.beatmapsets] == [10]
    assert broker.metadata.calls == [("metadata:beatmapset", "1000")]
    assert broker.metadata.force_refresh_calls == [True]


@pytest.mark.asyncio
async def test_beatmap_fetch_enqueue_routes_file_targets_to_file_job() -> None:
    """File target の enqueue が file job だけへ target type と key を渡す契約を検証する.

    Returns:
        None: metadata task の未使用と file task の記録を検証して完了する.
    """
    broker = _FakeBroker()

    await enqueue_beatmap_fetch(
        cast("AsyncBroker", cast("object", broker)),
        BeatmapFetchTarget.file_by_beatmap_id(1),
    )

    assert broker.metadata.calls == []
    assert broker.file.calls == [("file:beatmap", "1")]


def _direct_beatmapset(beatmapset_id: int) -> BeatmapSet:
    """Direct search external候補用のbeatmapsetを作る.

    Args:
        beatmapset_id (int): 作成するbeatmapset ID.

    Returns:
        BeatmapSet: 検索結果として返せるranked beatmapset.
    """
    return BeatmapSet(
        id=beatmapset_id,
        artist="Camellia",
        title="Title",
        creator="Mapper",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        beatmaps=(_direct_beatmap(beatmapset_id),),
        last_fetched_at=None,
        next_refresh_at=None,
    )


def _direct_beatmap(beatmapset_id: int) -> Beatmap:
    """Direct search external候補用のchild beatmapを作る.

    Args:
        beatmapset_id (int): 親beatmapset ID.

    Returns:
        Beatmap: 検索結果として返せるranked child beatmap.
    """
    return Beatmap(
        id=beatmapset_id * 10,
        beatmapset_id=beatmapset_id,
        checksum_md5=f"{beatmapset_id:032x}",
        mode=BeatmapMode.OSU,
        version="Normal",
        total_length=120,
        hit_length=100,
        max_combo=500,
        bpm=180.0,
        cs=4.0,
        od=8.0,
        ar=9.0,
        hp=6.0,
        difficulty_rating=5.0,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )
