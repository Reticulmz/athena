"""Beatmap file warmup requestのidentity policyを検証するtest module."""

from __future__ import annotations

from dataclasses import replace
from typing import final

from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.services.commands.beatmaps.file_warmup import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    RequestBeatmapFileWarmupUseCase,
)


@final
class RecordingWarmupResolver:
    """正常なresolve結果と呼出履歴を返すwarmup resolverのtest double.

    Attributes:
        calls (list[tuple[str, int | str, BeatmapResolveOptions | None]]): resolve呼出履歴.
        result (BeatmapResolveResult): 各resolve呼出で返す設定済みの結果.
    """

    def __init__(self) -> None:
        """保留結果を持つ空のresolver状態を初期化する."""
        self.calls: list[tuple[str, int | str, BeatmapResolveOptions | None]] = []
        self.result = _pending_result()

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """対象beatmap IDによるresolve要求を記録して設定済みの結果を返す.

        Args:
            beatmap_id (int): resolve対象のbeatmap ID.
            options (BeatmapResolveOptions | None): file取得要件を含む任意のresolve条件.

        Returns:
            BeatmapResolveResult: testで事前設定したresolve結果.
        """
        self.calls.append(("beatmap_id", beatmap_id, options))
        return self.result

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """対象checksumによるresolve要求を記録して設定済みの結果を返す.

        Args:
            checksum_md5 (str): resolve対象のMD5 checksum.
            options (BeatmapResolveOptions | None): file取得要件を含む任意のresolve条件.

        Returns:
            BeatmapResolveResult: testで事前設定したresolve結果.
        """
        self.calls.append(("checksum", checksum_md5, options))
        return self.result


@final
class FailingWarmupResolver:
    """診断情報を秘匿したresolver失敗を再現するtest double.

    Attributes:
        calls (list[tuple[str, int | str, BeatmapResolveOptions | None]]): resolve呼出履歴.
    """

    def __init__(self) -> None:
        """呼出履歴だけを保持する失敗用resolver状態を初期化する."""
        self.calls: list[tuple[str, int | str, BeatmapResolveOptions | None]] = []

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """対象beatmap IDのresolve後に診断用の失敗を送出する.

        Args:
            beatmap_id (int): resolve対象のbeatmap ID.
            options (BeatmapResolveOptions | None): file取得要件を含む任意のresolve条件.

        Raises:
            RuntimeError: resolver失敗時の構造化log処理を検証する場合.
        """
        self.calls.append(("beatmap_id", beatmap_id, options))
        raise RuntimeError("credential=secret replay bytes should not be logged")

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """対象checksumのresolve後に診断用の失敗を送出する.

        Args:
            checksum_md5 (str): resolve対象のMD5 checksum.
            options (BeatmapResolveOptions | None): file取得要件を含む任意のresolve条件.

        Raises:
            RuntimeError: resolver失敗時の構造化log処理を検証する場合.
        """
        self.calls.append(("checksum", checksum_md5, options))
        raise RuntimeError("raw payload should not be logged")


async def test_no_beatmap_identity_skips_without_resolver_call() -> None:
    """このidentity未指定のwarmupがresolverを呼ばずにskipする契約を検証する.

    beatmap IDとchecksumのないrequestを渡し, skip outcomeと構造化eventが記録されることを確認する.

    Returns:
        None: outcomeとeventを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
                user_id=2,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.SKIPPED_NO_IDENTITY
    assert result.entrance is BeatmapFileWarmupEntrance.STABLE_GETSCORES
    assert result.user_id == 2
    assert result.beatmap_id is None
    assert result.checksum_md5 is None
    assert result.reason == "no_beatmap_identity"
    assert resolver.calls == []

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "skipped_no_identity"
    assert events[0]["reason"] == "no_beatmap_identity"
    assert events[0]["entrance"] == "stable_getscores"


async def test_malformed_beatmap_identity_skips_without_resolver_call() -> None:
    """不正なidentityのwarmupがresolverを呼ばずにskipする契約を検証する.

    負のbeatmap IDと不正なchecksumを渡す.
    malformed identity用のoutcomeとeventが記録されることを確認する.

    Returns:
        None: outcomeとeventを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
                user_id=3,
                beatmap_id=-1,
                checksum_md5="not-an-md5",
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.SKIPPED_MALFORMED_IDENTITY
    assert result.entrance is BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE
    assert result.user_id == 3
    assert result.beatmap_id is None
    assert result.checksum_md5 is None
    assert result.reason == "malformed_beatmap_identity"
    assert resolver.calls == []

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "skipped_malformed_identity"
    assert events[0]["reason"] == "malformed_beatmap_identity"
    assert events[0]["entrance"] == "stable_status_change"


async def test_positive_beatmap_id_takes_priority_over_checksum() -> None:
    """有効なbeatmap IDがchecksumより優先される解決契約を検証する.

    両方のidentityを持つrequestを渡す.
    resolverがbeatmap IDをfile待機なしのoptionsとともに一度だけ受け取ることを確認する.

    Returns:
        None: resolverの呼出種別とoptionsを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    _ = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
            user_id=4,
            beatmap_id=75,
            checksum_md5="3B0AECD99EBA50FFC7BFF8DA117D0E06",
        )
    )

    assert len(resolver.calls) == 1
    method, value, options = resolver.calls[0]
    assert method == "beatmap_id"
    assert value == 75
    assert options is not None
    assert options.require_osu_file is True
    assert options.wait_timeout_seconds == 0.0


async def test_checksum_identity_is_normalized_before_resolver_call() -> None:
    """対象checksum identityがresolver呼出前に正規化される契約を検証する.

    大文字を含むMD5 checksumを渡す.
    小文字化した値とfile待機なしのoptionsでresolveされることを確認する.

    Returns:
        None: 正規化後のresolver入力を検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    _ = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=5,
            checksum_md5="3B0AECD99EBA50FFC7BFF8DA117D0E06",
        )
    )

    assert len(resolver.calls) == 1
    method, value, options = resolver.calls[0]
    assert method == "checksum"
    assert value == "3b0aecd99eba50ffc7bff8da117d0e06"
    assert options is not None
    assert options.require_osu_file is True
    assert options.wait_timeout_seconds == 0.0


async def test_available_file_maps_to_already_available_noop() -> None:
    """利用可能なfileがalready availableのno-opへ対応付けられる契約を検証する.

    AVAILABLE file状態の既知beatmapをresolveする.
    outcomeと構造化eventがfile_available理由を持つことを確認する.

    Returns:
        None: no-op outcomeとeventを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    resolver.result = _known_result(beatmap_id=42, file_status=BeatmapFileState.AVAILABLE)
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
                user_id=6,
                beatmap_id=42,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.ALREADY_AVAILABLE
    assert result.beatmap_id == 42
    assert result.checksum_md5 is None
    assert result.reason == "file_available"
    assert len(resolver.calls) == 1

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "already_available"
    assert events[0]["reason"] == "file_available"


async def test_available_file_uses_noop_reason_when_metadata_is_stale() -> None:
    """対象metadataがstaleでも利用可能なfileがno-opになる契約を検証する.

    AVAILABLE file状態とstale理由を返すresolverを使う.
    file_available理由のalready available outcomeになることを確認する.

    Returns:
        None: outcome理由とeventを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    resolver.result = replace(
        _known_result(beatmap_id=42, file_status=BeatmapFileState.AVAILABLE),
        reason="stale",
    )
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
                user_id=6,
                beatmap_id=42,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.ALREADY_AVAILABLE
    assert result.reason == "file_available"
    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    assert events[0]["outcome"] == "already_available"
    assert events[0]["reason"] == "file_available"


async def test_known_beatmap_missing_file_maps_to_requested() -> None:
    """対象fileのない既知beatmapがfile requestへ対応付けられる契約を検証する.

    MISSING file状態の既知beatmapをresolveする.
    requested outcomeとfile_missing理由になることを確認する.

    Returns:
        None: request outcomeを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    resolver.result = _known_result(beatmap_id=43, file_status=BeatmapFileState.MISSING)
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    result = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=7,
            beatmap_id=43,
        )
    )

    assert result.outcome is BeatmapFileWarmupOutcome.REQUESTED
    assert result.beatmap_id == 43
    assert result.reason == "file_missing"


async def test_checksum_only_unresolved_beatmap_maps_to_metadata_pending() -> None:
    """未解決のchecksum identityがmetadata pendingへ対応付けられる契約を検証する.

    checksumだけを持つrequestでpending結果を返す.
    beatmap IDなしのmetadata pending outcomeになることを確認する.

    Returns:
        None: pending outcomeとchecksumを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = RecordingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    result = await use_case.execute(
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=8,
            checksum_md5="3b0aecd99eba50ffc7bff8da117d0e06",
        )
    )

    assert result.outcome is BeatmapFileWarmupOutcome.METADATA_PENDING
    assert result.beatmap_id is None
    assert result.checksum_md5 == "3b0aecd99eba50ffc7bff8da117d0e06"
    assert result.reason == "pending"


async def test_resolver_failure_returns_failed_and_logs_sanitized_diagnostics() -> None:
    """このresolver失敗が機密値を出さないfailed outcomeになる契約を検証する.

    失敗するresolverを使い, failed outcomeとexception種別だけがeventに記録されることを確認する.

    Returns:
        None: 失敗結果とsanitize済みeventを検証して完了し, 呼び出し側へ値を返さない.
    """
    resolver = FailingWarmupResolver()
    use_case = RequestBeatmapFileWarmupUseCase(resolver)

    with capture_logs() as logs:
        result = await use_case.execute(
            BeatmapFileWarmupRequest(
                entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
                user_id=9,
                beatmap_id=44,
            )
        )

    assert result.outcome is BeatmapFileWarmupOutcome.FAILED
    assert result.beatmap_id == 44
    assert result.checksum_md5 is None
    assert result.reason == "resolver_failure"

    events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(events) == 1
    event = events[0]
    assert event["outcome"] == "failed"
    assert event["reason"] == "resolver_failure"
    assert event["exception_type"] == "RuntimeError"
    assert "credential" not in event
    assert "raw_payload" not in event
    assert "replay_bytes" not in event


def _pending_result() -> BeatmapResolveResult:
    """対象metadata取得中でfile未取得のresolve結果を作る.

    Returns:
        BeatmapResolveResult: PENDING_FETCHとMISSING file状態を持つtest用の結果.
    """
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
        reason="pending",
    )


def _known_result(
    *,
    beatmap_id: int,
    file_status: BeatmapFileState,
) -> BeatmapResolveResult:
    """指定したfile状態を持つ既知beatmapのresolve結果を作る.

    Args:
        beatmap_id (int): 生成するbeatmapの識別子.
        file_status (BeatmapFileState): 生成するbeatmapのfile取得状態.

    Returns:
        BeatmapResolveResult: 指定状態のbeatmapと対応する理由を含むtest用の結果.
    """
    beatmap = Beatmap(
        id=beatmap_id,
        beatmapset_id=24,
        checksum_md5="3b0aecd99eba50ffc7bff8da117d0e06",
        mode=BeatmapMode.OSU,
        version="Insane",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=file_status,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )
    return BeatmapResolveResult(
        beatmap=beatmap,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.FRESH,
        file_status=file_status,
        source=BeatmapMetadataSource.MIRROR,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="file_available" if file_status is BeatmapFileState.AVAILABLE else "file_missing",
    )
