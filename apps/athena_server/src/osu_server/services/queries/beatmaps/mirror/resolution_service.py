"""cache-firstでbeatmapとbeatmapsetを解決するquery serviceを定義する.

score submissionとleaderboardとrank managementなどのcallerへ構造化した結果stateを返す.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileState,
    BeatmapFreshnessDecision,
    BeatmapFreshnessPolicy,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSet,
    BeatmapSetResolveResult,
    BeatmapSourceVerification,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
    from osu_server.services.queries.beatmaps.mirror.eligibility_service import (
        BeatmapEligibilityService,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


_POLL_INTERVAL: float = 0.05


class BeatmapMirrorService:
    """cache-firstでbeatmapとbeatmapsetを解決してfreshnessとeligibilityを投影する.

    Attributes:
        _repository (BeatmapQueryRepository): cached beatmapとfetch stateを読み取るrepository.
        _eligibility (BeatmapEligibilityService): score受付可否を投影するservice.
        _freshness (BeatmapFreshnessPolicy): metadataがstaleかを判定するpolicy.
        _mirror_trust_enabled (bool): mirror由来statusを信頼するか.
        _official_sources_available (bool): official metadata sourceが現在利用可能か.
        _enqueue_refresh (Callable[[BeatmapFetchTarget], Awaitable[None]] | None): optionalな
            background metadataまたはfile refresh callback.

    Notes:
        enqueue_refreshはoptionalであり未設定時はcache missまたはstale状態をresultとして返す.
    """

    _repository: BeatmapQueryRepository
    _eligibility: BeatmapEligibilityService
    _freshness: BeatmapFreshnessPolicy
    _mirror_trust_enabled: bool
    _official_sources_available: bool
    _enqueue_refresh: Callable[[BeatmapFetchTarget], Awaitable[None]] | None

    def __init__(
        self,
        repository: BeatmapQueryRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        *,
        mirror_trust_enabled: bool = False,
        official_sources_available: bool = True,
        enqueue_refresh: Callable[[BeatmapFetchTarget], Awaitable[None]] | None = None,
    ) -> None:
        """read-only解決に必要なrepositoryとpolicyとoptional refresh callbackを保持する.

        Args:
            repository (BeatmapQueryRepository): cached beatmapとfetch stateを読み取るrepository.
            eligibility_service (BeatmapEligibilityService): score受付可否を投影するservice.
            freshness_policy (BeatmapFreshnessPolicy): metadata freshnessを判定するpolicy.
            mirror_trust_enabled (bool): mirror由来statusを信頼するか.
            official_sources_available (bool): official metadata sourceが現在利用可能か.
            enqueue_refresh (Callable[[BeatmapFetchTarget], Awaitable[None]] | None):
                background refreshを要求するoptional callback.
        """
        self._repository = repository
        self._eligibility = eligibility_service
        self._freshness = freshness_policy
        self._mirror_trust_enabled = mirror_trust_enabled
        self._official_sources_available = official_sources_available
        self._enqueue_refresh = enqueue_refresh  # wired in task 5.2

    # ------------------------------------------------------------------
    # Public resolve methods
    # ------------------------------------------------------------------

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap IDからcache-firstに一件のbeatmapを解決する.

        Args:
            beatmap_id (int): 解決するbeatmapのID.
            options (BeatmapResolveOptions | None): file要件とrefresh要件とwait上限を持つoption.

        Returns:
            BeatmapResolveResult: known beatmapまたはfetch stateを持つunavailable結果.

        Notes:
            cache missまたはstale stateでは設定済みenqueue_refresh callbackを呼び出す場合がある.
        """
        opts = options or BeatmapResolveOptions()
        now = datetime.now(UTC)

        beatmap = await self._repository.get_beatmap(beatmap_id)
        if beatmap is not None:
            return await self._known_beatmap_result(beatmap, opts, now)

        metadata_target = BeatmapFetchTarget.metadata_by_beatmap_id(beatmap_id)
        file_target = BeatmapFetchTarget.file_by_beatmap_id(beatmap_id)

        await self._try_enqueue(metadata_target)
        if opts.require_osu_file:
            await self._try_enqueue(file_target)

        if opts.wait_timeout_seconds > 0:
            beatmap = await self._wait_for_beatmap(beatmap_id, opts)
            if beatmap is not None:
                return await self._known_beatmap_result(beatmap, opts, now)

        return await self._unknown_result(
            metadata_target=metadata_target,
            file_target=file_target,
            opts=opts,
            now=now,
        )

    async def resolve_by_beatmapset_id(
        self,
        beatmapset_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapSetResolveResult:
        """Beatmapset IDからcache-firstに一件のbeatmapsetを解決する.

        Args:
            beatmapset_id (int): 解決するbeatmapsetのID.
            options (BeatmapResolveOptions | None): refresh要件とwait上限を持つoption.

        Returns:
            BeatmapSetResolveResult: known beatmapsetまたはfetch stateを持つunavailable結果.

        Notes:
            cache missまたはstale stateでは設定済みenqueue_refresh callbackを呼び出す場合がある.
        """
        opts = options or BeatmapResolveOptions()
        now = datetime.now(UTC)

        beatmapset = await self._repository.get_beatmapset(beatmapset_id)
        if beatmapset is not None:
            return _set_result(beatmapset)

        metadata_target = BeatmapFetchTarget.metadata_by_beatmapset_id(beatmapset_id)

        await self._try_enqueue(metadata_target)

        if opts.wait_timeout_seconds > 0:
            beatmapset = await self._wait_for_beatmapset(beatmapset_id, opts)
            if beatmapset is not None:
                return _set_result(beatmapset)

        return await self._unknown_set_result(
            metadata_target=metadata_target,
            opts=opts,
            now=now,
        )

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """MD5 checksumからcache-firstに一件のbeatmapを解決する.

        Args:
            checksum_md5 (str): 解決するbeatmap contentのMD5 checksum.
            options (BeatmapResolveOptions | None): file要件とrefresh要件とwait上限を持つoption.

        Returns:
            BeatmapResolveResult: known beatmapまたはfetch stateを持つunavailable結果.

        Notes:
            cache missまたはstale stateでは設定済みenqueue_refresh callbackを呼び出す場合がある.
        """
        opts = options or BeatmapResolveOptions()
        now = datetime.now(UTC)

        beatmap = await self._repository.get_beatmap_by_checksum(checksum_md5)
        if beatmap is not None:
            return await self._known_beatmap_result(beatmap, opts, now)

        metadata_target = BeatmapFetchTarget.metadata_by_checksum(checksum_md5)

        await self._try_enqueue(metadata_target)

        if opts.wait_timeout_seconds > 0:
            beatmap = await self._wait_for_beatmap_by_checksum(checksum_md5, opts)
            if beatmap is not None:
                return await self._known_beatmap_result(beatmap, opts, now)

        return await self._unknown_result(
            metadata_target=metadata_target,
            file_target=None,
            opts=opts,
            now=now,
        )

    # ------------------------------------------------------------------
    # Known beatmap result builder
    # ------------------------------------------------------------------

    async def _known_beatmap_result(
        self,
        beatmap: Beatmap,
        opts: BeatmapResolveOptions,
        now: datetime,
    ) -> BeatmapResolveResult:
        """Cached beatmapからfreshnessとfile stateを反映した解決結果を作る.

        Args:
            beatmap (Beatmap): repositoryから取得したcached beatmap.
            opts (BeatmapResolveOptions): fileとrefreshの解決要件.
            now (datetime): freshness判定に使うUTC現在時刻.

        Returns:
            BeatmapResolveResult: eligibilityとfetch statusを含むknown beatmap結果.
        """
        decision = self._freshness.evaluate(
            beatmap,
            now=now,
            official_sources_available=self._official_sources_available,
            force_refresh=opts.force_refresh,
        )

        if decision.should_refresh:
            await self._try_enqueue(
                BeatmapFetchTarget.metadata_by_beatmap_id(
                    beatmap.id,
                    force_refresh=opts.force_refresh,
                )
            )

        if opts.require_osu_file and beatmap.file_state is not BeatmapFileState.AVAILABLE:
            await self._try_enqueue(BeatmapFetchTarget.file_by_beatmap_id(beatmap.id))

        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)
        eligibility = self._eligibility.evaluate(
            beatmap, mirror_trust_enabled=self._mirror_trust_enabled
        )

        reason = _result_reason(decision, opts, beatmap)

        return BeatmapResolveResult(
            beatmap=beatmap,
            beatmapset=beatmapset,
            eligibility=eligibility,
            metadata_status=_derive_metadata_status(beatmap, decision),
            file_status=beatmap.file_state,
            source=beatmap.official_status_source,
            verified=beatmap.official_status_verified is BeatmapSourceVerification.VERIFIED,
            last_fetched_at=beatmap.last_fetched_at,
            next_refresh_at=beatmap.next_refresh_at,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Enqueue helper
    # ------------------------------------------------------------------

    async def _try_enqueue(self, target: BeatmapFetchTarget) -> None:
        """Refresh callbackが設定されている場合だけfetch targetをenqueueする.

        Args:
            target (BeatmapFetchTarget): metadataまたはfile refreshを要求するtarget.

        Returns:
            None: callback未設定時は何もせず値を返さない.
        """
        if self._enqueue_refresh is not None:
            await self._enqueue_refresh(target)

    # ------------------------------------------------------------------
    # Bounded wait helpers
    # ------------------------------------------------------------------

    async def _wait_for_beatmap(
        self,
        beatmap_id: int,
        opts: BeatmapResolveOptions,
    ) -> Beatmap | None:
        """wait上限までrepositoryをpollしてbeatmapの出現を待つ.

        Args:
            beatmap_id (int): 出現を待つbeatmapのID.
            opts (BeatmapResolveOptions): wait_timeout_secondsを提供するoption.

        Returns:
            Beatmap | None: wait中に取得したbeatmap. 上限到達時はNone.
        """
        deadline = datetime.now(UTC).timestamp() + opts.wait_timeout_seconds
        while True:
            remaining = deadline - datetime.now(UTC).timestamp()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(_POLL_INTERVAL, max(0.0, remaining)))
            beatmap = await self._repository.get_beatmap(beatmap_id)
            if beatmap is not None:
                return beatmap

    async def _wait_for_beatmapset(
        self,
        beatmapset_id: int,
        opts: BeatmapResolveOptions,
    ) -> BeatmapSet | None:
        """wait上限までrepositoryをpollしてbeatmapsetの出現を待つ.

        Args:
            beatmapset_id (int): 出現を待つbeatmapsetのID.
            opts (BeatmapResolveOptions): wait_timeout_secondsを提供するoption.

        Returns:
            BeatmapSet | None: wait中に取得したbeatmapset. 上限到達時はNone.
        """
        deadline = datetime.now(UTC).timestamp() + opts.wait_timeout_seconds
        while True:
            remaining = deadline - datetime.now(UTC).timestamp()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(_POLL_INTERVAL, max(0.0, remaining)))
            beatmapset = await self._repository.get_beatmapset(beatmapset_id)
            if beatmapset is not None:
                return beatmapset

    async def _wait_for_beatmap_by_checksum(
        self,
        checksum_md5: str,
        opts: BeatmapResolveOptions,
    ) -> Beatmap | None:
        """wait上限までrepositoryをpollしてchecksum一致beatmapの出現を待つ.

        Args:
            checksum_md5 (str): 出現を待つbeatmap contentのMD5 checksum.
            opts (BeatmapResolveOptions): wait_timeout_secondsを提供するoption.

        Returns:
            Beatmap | None: wait中に取得したbeatmap. 上限到達時はNone.
        """
        deadline = datetime.now(UTC).timestamp() + opts.wait_timeout_seconds
        while True:
            remaining = deadline - datetime.now(UTC).timestamp()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(_POLL_INTERVAL, max(0.0, remaining)))
            beatmap = await self._repository.get_beatmap_by_checksum(checksum_md5)
            if beatmap is not None:
                return beatmap

    # ------------------------------------------------------------------
    # Unknown result builders
    # ------------------------------------------------------------------

    async def _unknown_result(
        self,
        *,
        metadata_target: BeatmapFetchTarget,
        file_target: BeatmapFetchTarget | None,
        opts: BeatmapResolveOptions,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
        now: datetime,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
    ) -> BeatmapResolveResult:
        """未発見beatmapのmetadata recordとfile recordから解決結果を作る.

        Args:
            metadata_target (BeatmapFetchTarget): metadata fetch stateを取得するtarget.
            file_target (BeatmapFetchTarget | None): file fetch stateを取得するoptional target.
            opts (BeatmapResolveOptions): 将来のunavailable result投影に使うoption.
            now (datetime): 将来のunavailable result投影に使うUTC現在時刻.

        Returns:
            BeatmapResolveResult: 未発見beatmapと既知またはpending fetch stateを持つ結果.

        Notes:
            optsとnowはtask 5.2での拡張用に受け取るが現在の投影には影響しない.
        """
        metadata_record = await self._repository.get_fetch_state(metadata_target)

        if metadata_record is None:
            return BeatmapResolveResult(
                beatmap=None,
                beatmapset=None,
                eligibility=None,
                metadata_status=BeatmapFetchState.PENDING_FETCH,
                file_status=BeatmapFileState.MISSING,
                source=None,
                verified=False,
                last_fetched_at=None,
                next_refresh_at=None,
                reason="unsolicited",
            )

        file_state = await self._lookup_file_state(file_target)
        return BeatmapResolveResult(
            beatmap=None,
            beatmapset=None,
            eligibility=None,
            metadata_status=metadata_record.status,
            file_status=file_state,
            source=None,
            verified=False,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=_fetch_record_reason(metadata_record),
        )

    async def _unknown_set_result(
        self,
        *,
        metadata_target: BeatmapFetchTarget,
        opts: BeatmapResolveOptions,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
        now: datetime,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
    ) -> BeatmapSetResolveResult:
        """未発見beatmapsetのmetadata recordから解決結果を作る.

        Args:
            metadata_target (BeatmapFetchTarget): metadata fetch stateを取得するtarget.
            opts (BeatmapResolveOptions): 将来のunavailable result投影に使うoption.
            now (datetime): 将来のunavailable result投影に使うUTC現在時刻.

        Returns:
            BeatmapSetResolveResult: 未発見beatmapsetと既知またはpending fetch stateを持つ結果.

        Notes:
            optsとnowはtask 5.2での拡張用に受け取るが現在の投影には影響しない.
        """
        metadata_record = await self._repository.get_fetch_state(metadata_target)

        if metadata_record is None:
            return BeatmapSetResolveResult(
                beatmapset=None,
                metadata_status=BeatmapFetchState.PENDING_FETCH,
                source=None,
                verified=False,
                last_fetched_at=None,
                next_refresh_at=None,
                reason="unsolicited",
            )

        return BeatmapSetResolveResult(
            beatmapset=None,
            metadata_status=metadata_record.status,
            source=None,
            verified=False,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=_fetch_record_reason(metadata_record),
        )

    async def _lookup_file_state(
        self,
        file_target: BeatmapFetchTarget | None,
    ) -> BeatmapFileState:
        """未発見beatmapに対応するfile fetch stateを判定する.

        Args:
            file_target (BeatmapFetchTarget | None): file fetch stateを取得するoptional target.

        Returns:
            BeatmapFileState: targetまたはfetch recordがない場合はMISSING. それ以外は
                record由来state.
        """
        if file_target is None:
            return BeatmapFileState.MISSING

        record = await self._repository.get_fetch_state(file_target)
        if record is None:
            return BeatmapFileState.MISSING

        return _file_state_from_fetch_status(record.status)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _derive_metadata_status(
    beatmap: Beatmap,
    decision: BeatmapFreshnessDecision,
) -> BeatmapFetchState:
    """Beatmap fetch stateとfreshness decisionからmetadata statusを導出する.

    Args:
        beatmap (Beatmap): current metadata fetch stateを持つbeatmap.
        decision (BeatmapFreshnessDecision): staleかrefreshすべきかを表すdecision.

    Returns:
        BeatmapFetchState: pendingとfailedを優先し必要ならSTALEへ変換したstatus.
    """
    if beatmap.metadata_fetch_state is BeatmapFetchState.PENDING_FETCH:
        return BeatmapFetchState.PENDING_FETCH
    if beatmap.metadata_fetch_state is BeatmapFetchState.FAILED:
        return BeatmapFetchState.FAILED
    if decision.should_refresh:
        return BeatmapFetchState.STALE
    return BeatmapFetchState.FRESH


def _result_reason(
    decision: BeatmapFreshnessDecision,
    opts: BeatmapResolveOptions,
    beatmap: Beatmap,
) -> str | None:
    """解決結果に表示するhuman-readableなreasonを導出する.

    Args:
        decision (BeatmapFreshnessDecision): freshness判定のreasonを持つdecision.
        opts (BeatmapResolveOptions): osu file要件を持つoption.
        beatmap (Beatmap): file stateを持つresolved beatmap.

    Returns:
        str | None: file要件不足またはfreshness由来のreason. reason不要時はNone.
    """
    if opts.require_osu_file and beatmap.file_state is not BeatmapFileState.AVAILABLE:
        return "osu_file_required_but_unavailable"
    return decision.reason


def _fetch_record_reason(record: object) -> str | None:
    """Fetch recordのstateからunavailable result用reasonを導出する.

    Args:
        record (object): statusとoptionalなlast_errorを持つfetch record.

    Returns:
        str | None: failedまたはpending状態のreason. それ以外はNone.
    """
    status: object = getattr(record, "status", None)
    if status is BeatmapFetchState.FAILED:
        error: object = getattr(record, "last_error", None)
        return error if isinstance(error, str) else "fetch_failed"
    if status is BeatmapFetchState.PENDING_FETCH:
        return "pending_fetch"
    return None


def _file_state_from_fetch_status(status: BeatmapFetchState) -> BeatmapFileState:
    """Metadata fetch stateをunknown beatmap用のfile stateへ変換する.

    Args:
        status (BeatmapFetchState): file targetに保存されたfetch state.

    Returns:
        BeatmapFileState: pendingまたはfailedを維持しそれ以外はMISSINGとするfile state.
    """
    if status is BeatmapFetchState.PENDING_FETCH:
        return BeatmapFileState.PENDING_FETCH
    if status is BeatmapFetchState.FAILED:
        return BeatmapFileState.FAILED
    return BeatmapFileState.MISSING


def _set_result(beatmapset: BeatmapSet) -> BeatmapSetResolveResult:
    """knownかつcachedなbeatmapsetのread-only解決結果を作る.

    Args:
        beatmapset (BeatmapSet): repositoryから取得したcached beatmapset.

    Returns:
        BeatmapSetResolveResult: fresh metadata stateを持つresolved beatmapset結果.
    """
    return BeatmapSetResolveResult(
        beatmapset=beatmapset,
        metadata_status=BeatmapFetchState.FRESH,
        source=beatmapset.official_status_source,
        verified=beatmapset.official_status_verified is BeatmapSourceVerification.VERIFIED,
        last_fetched_at=beatmapset.last_fetched_at,
        next_refresh_at=beatmapset.next_refresh_at,
        reason=None,
    )
