"""in-memory Beatmap command repositoryの契約を検証するtest."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

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
from osu_server.repositories.memory.commands.beatmaps import (
    DuplicateBeatmapChecksumError,
    InMemoryBeatmapCommandRepository,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"
_OTHER_CHECKSUM = "fedcba9876543210fedcba9876543210"


def _make_beatmap(
    *,
    beatmap_id: int = 2_000,
    beatmapset_id: int = 1_000,
    checksum_md5: str = _CHECKSUM,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    local_status_override: LocalBeatmapStatus | None = None,
    local_status_override_changed_at: datetime | None = None,
    official_last_updated_at: datetime | None = None,
    file_attachment: BeatmapFileAttachment | None = None,
) -> Beatmap:
    """Command repository testで使うBeatmap fixtureを構築する.

    Args:
        beatmap_id (int): BeatmapのID.
        beatmapset_id (int): 親BeatmapSetのID.
        checksum_md5 (str): Beatmap revisionを特定するMD5 checksum.
        official_status (BeatmapRankStatus): official metadata由来のrank status.
        local_status_override (LocalBeatmapStatus | None): local status override. Noneなら未設定.
        local_status_override_changed_at (datetime | None): local overrideを変更した時刻.
            Noneなら未記録.
        official_last_updated_at (datetime | None): sourceが報告した最終更新時刻.
            Noneなら未提供.
        file_attachment (BeatmapFileAttachment | None): current osu file attachment.
            Noneならfile未取得.

    Returns:
        Beatmap: fixed difficulty/metadata値を持つBeatmap fixture.
    """
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
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
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=(
            BeatmapFileState.AVAILABLE if file_attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=file_attachment,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
        official_last_updated_at=official_last_updated_at,
        local_status_override_changed_at=local_status_override_changed_at,
    )


def _make_beatmapset(
    *beatmaps: Beatmap,
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
) -> BeatmapSet:
    """指定Beatmap群を持つBeatmapSet snapshot fixtureを構築する.

    Args:
        beatmaps (Beatmap): snapshotへ含めるchild Beatmap.
        status (BeatmapRankStatus): BeatmapSetのofficial rank status.

    Returns:
        BeatmapSet: fixed metadata/timestampsと指定childを持つsnapshot fixture.
    """
    return BeatmapSet(
        id=1_000,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=beatmaps,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_attachment(
    *,
    beatmap_id: int = 2_000,
    checksum_md5: str = _CHECKSUM,
    blob_id: int = 55,
) -> BeatmapFileAttachment:
    """Beatmapのcurrent osu file attachment fixtureを構築する.

    Args:
        beatmap_id (int): attachmentを関連付けるBeatmapのID.
        checksum_md5 (str): attachment fileを特定するMD5 checksum.
        blob_id (int): attachmentが参照するblobのID.

    Returns:
        BeatmapFileAttachment: official sourceと検証済みtimestampsを持つattachment fixture.
    """
    return BeatmapFileAttachment(
        beatmap_id=beatmap_id,
        blob_id=blob_id,
        checksum_md5=checksum_md5,
        source=BeatmapFileSource.OFFICIAL,
        original_filename=f"{beatmap_id}.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
    )


def _repo() -> InMemoryBeatmapCommandRepository:
    """Empty stateを持つin-memory Beatmap command repositoryを構築する.

    Returns:
        InMemoryBeatmapCommandRepository: 各testで独立して利用するrepository fixture.
    """
    return InMemoryBeatmapCommandRepository(InMemoryCommandRepositoryState())


def test_in_memory_beatmap_repository_satisfies_contract() -> None:
    """in-memory Beatmap repositoryがcommand portを実装する契約を検証する.

    empty stateからrepositoryを構築してBeatmapCommandRepositoryとして判定する.
    command callerがinterface型でrepositoryを利用できることを確認する.

    Returns:
        None: repository port実装のruntime contractを検証して完了する.
    """
    repo = _repo()

    assert isinstance(repo, BeatmapCommandRepository)


async def test_saves_and_resolves_beatmaps_by_id_set_id_and_checksum() -> None:
    """snapshot保存後にBeatmap/BeatmapSetを全lookup keyで取得する契約を検証する.

    一つのBeatmapを持つBeatmapSet snapshotを保存してID/checksum/set ID lookupを実行する.
    各lookupが同じBeatmapとchildを含むBeatmapSetを返すことを確認する.

    Returns:
        None: snapshot persistenceとprimary/secondary lookupを検証して完了する.
    """
    repo = _repo()
    beatmap = _make_beatmap()

    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    assert await repo.get_beatmap(2_000) == beatmap
    assert await repo.get_beatmap_by_checksum(_CHECKSUM) == beatmap
    beatmapset = await repo.get_beatmapset(1_000)
    assert beatmapset is not None
    assert beatmapset.beatmaps == (beatmap,)


async def test_save_rejects_checksum_reuse_for_different_beatmap() -> None:
    """既存Beatmapと異なるIDによるchecksum再利用を拒否する契約を検証する.

    保存済みsnapshotと同じMD5 checksumを別Beatmap IDで含むsnapshotを保存する.
    checksumと既存Beatmap IDを保持するDuplicateBeatmapChecksumErrorが発生することを確認する.

    Returns:
        None: cross-snapshot checksum一意性を検証して完了する.
    """
    repo = _repo()
    await repo.save_beatmapset_snapshot(_make_beatmapset(_make_beatmap()))

    with pytest.raises(DuplicateBeatmapChecksumError) as exc_info:
        await repo.save_beatmapset_snapshot(
            _make_beatmapset(_make_beatmap(beatmap_id=2_001, checksum_md5=_CHECKSUM))
        )

    assert exc_info.value.checksum_md5 == _CHECKSUM
    assert exc_info.value.existing_beatmap_id == 2_000


async def test_save_rejects_duplicate_checksum_inside_same_snapshot() -> None:
    """一つのsnapshot内で異なるBeatmap IDがchecksumを共有できない契約を検証する.

    同一MD5 checksumを持つ二つのchild Beatmapを含むsnapshotを保存する.
    DuplicateBeatmapChecksumErrorが発生しpartial stateが保存されないことを確認する.

    Returns:
        None: intra-snapshot checksum一意性とatomic validationを検証して完了する.
    """
    repo = _repo()

    with pytest.raises(DuplicateBeatmapChecksumError) as exc_info:
        await repo.save_beatmapset_snapshot(
            _make_beatmapset(
                _make_beatmap(beatmap_id=2_000, checksum_md5=_CHECKSUM),
                _make_beatmap(beatmap_id=2_001, checksum_md5=_CHECKSUM),
            )
        )

    assert exc_info.value.checksum_md5 == _CHECKSUM
    assert exc_info.value.existing_beatmap_id == 2_000
    assert await repo.get_beatmap(2_000) is None
    assert await repo.get_beatmap(2_001) is None


async def test_official_refresh_preserves_existing_local_override() -> None:
    """Official metadata refreshが既存local status overrideを保持する契約を検証する.

    local RANKED overrideを持つPENDING Beatmapを保存後にLOVED official snapshotでrefreshする.
    official statusはLOVEDへ更新されることを確認する.
    local override/変更時刻/effective statusが保持されることを確認する.

    Returns:
        None: official/local statusの所有境界を検証して完了する.
    """
    repo = _repo()
    override_changed_at = datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC)
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(
            _make_beatmap(
                official_status=BeatmapRankStatus.PENDING,
                local_status_override=LocalBeatmapStatus.RANKED,
                local_status_override_changed_at=override_changed_at,
            )
        )
    )

    await repo.save_beatmapset_snapshot(
        _make_beatmapset(
            _make_beatmap(official_status=BeatmapRankStatus.LOVED),
            status=BeatmapRankStatus.LOVED,
        )
    )

    refreshed = await repo.get_beatmap(2_000)
    assert refreshed is not None
    assert refreshed.official_status is BeatmapRankStatus.LOVED
    assert refreshed.local_status_override is LocalBeatmapStatus.RANKED
    assert refreshed.local_status_override_changed_at == override_changed_at
    assert refreshed.effective_status is BeatmapRankStatus.RANKED


async def test_official_refresh_preserves_existing_last_updated_when_source_omits_it() -> None:
    """sourceが時刻を省略するofficial refreshが既存最終更新時刻を保持する契約を検証する.

    official_last_updated_atを持つsnapshotを保存して時刻なしの同一snapshotでrefreshする.
    保存済みBeatmapが最初のofficial_last_updated_atを返すことを確認する.

    Returns:
        None: omitted source timestampに対するmetadata保持を検証して完了する.
    """
    repo = _repo()
    official_last_updated_at = datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC)
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(official_last_updated_at=official_last_updated_at))
    )

    await repo.save_beatmapset_snapshot(_make_beatmapset(_make_beatmap()))

    refreshed = await repo.get_beatmap(2_000)
    assert refreshed is not None
    assert refreshed.official_last_updated_at == official_last_updated_at


async def test_increment_submission_counts_returns_cumulative_values() -> None:
    """Submission count更新がplay/pass countを累積して返す契約を検証する.

    未登録Beatmap IDへfailedとpassed submissionを順に記録する.
    play countは2まで増えpass countはpassed submissionだけを数えることを確認する.

    Returns:
        None: submission countの累積計算を検証して完了する.
    """
    repo = _repo()

    failed = await repo.increment_submission_counts(2_000, passed=False)
    passed = await repo.increment_submission_counts(2_000, passed=True)

    assert failed.play_count == 1
    assert failed.pass_count == 0
    assert passed.play_count == 2
    assert passed.pass_count == 1


async def test_can_set_local_override_without_changing_official_status() -> None:
    """Local override設定がofficial statusを変更しない契約を検証する.

    PENDING official Beatmapを保存してlocal RANKED overrideを設定する.
    official statusはPENDINGのままoverride/変更時刻/effective statusが更新されることを確認する.

    Returns:
        None: local status overrideの独立した保存を検証して完了する.
    """
    repo = _repo()
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(official_status=BeatmapRankStatus.PENDING))
    )

    updated = await repo.set_local_status_override(2_000, LocalBeatmapStatus.RANKED)

    assert updated.official_status is BeatmapRankStatus.PENDING
    assert updated.local_status_override is LocalBeatmapStatus.RANKED
    assert updated.local_status_override_changed_at is not None
    assert updated.effective_status is BeatmapRankStatus.RANKED


async def test_clearing_local_override_clears_changed_at() -> None:
    """Local override解除が対応する変更時刻も消す契約を検証する.

    PENDING BeatmapへRANKED overrideを設定して時刻が記録された状態を作る.
    None overrideへ更新後にoverrideと変更時刻の両方がNoneになることを確認する.

    Returns:
        None: local override解除時のpaired state cleanupを検証して完了する.
    """
    repo = _repo()
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(official_status=BeatmapRankStatus.PENDING))
    )
    ranked = await repo.set_local_status_override(2_000, LocalBeatmapStatus.RANKED)
    assert ranked.local_status_override_changed_at is not None

    cleared = await repo.set_local_status_override(2_000, None)

    assert cleared.local_status_override is None
    assert cleared.local_status_override_changed_at is None


async def test_attachments_are_idempotent_and_update_current_file_state() -> None:
    """Osu file attachment追加がidempotentでcurrent file stateを更新する契約を検証する.

    保存済みBeatmapへattachmentを追加し同じkeyで異なるblob IDのattachmentを再追加する.
    両操作が最初のattachmentを返すことを確認する.
    Beatmapのfile state/current attachmentをAVAILABLEへ更新することを確認する.

    Returns:
        None: attachment idempotencyとcurrent file metadata更新を検証して完了する.
    """
    repo = _repo()
    await repo.save_beatmapset_snapshot(_make_beatmapset(_make_beatmap()))
    attachment = _make_attachment()

    first = await repo.attach_osu_file(attachment)
    duplicate = await repo.attach_osu_file(replace(attachment, blob_id=99))

    assert first == attachment
    assert duplicate == attachment
    assert await repo.get_current_file_attachment(2_000) == attachment
    beatmap = await repo.get_beatmap(2_000)
    assert beatmap is not None
    assert beatmap.file_state is BeatmapFileState.AVAILABLE
    assert beatmap.file_attachment == attachment


async def test_official_refresh_preserves_existing_file_attachment() -> None:
    """Official refreshが既存osu file attachmentを保持する契約を検証する.

    attachment付きBeatmap snapshotを保存してattachmentなしのLOVED snapshotでrefreshする.
    refresh後もfile stateがAVAILABLEで同じattachmentを参照することを確認する.

    Returns:
        None: official metadataとlocal file stateの保持境界を検証して完了する.
    """
    repo = _repo()
    attachment = _make_attachment()
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(file_attachment=attachment))
    )

    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(official_status=BeatmapRankStatus.LOVED))
    )

    refreshed = await repo.get_beatmap(2_000)
    assert refreshed is not None
    assert refreshed.file_state is BeatmapFileState.AVAILABLE
    assert refreshed.file_attachment == attachment


async def test_fetch_pending_marker_is_idempotent_until_completed() -> None:
    """Pending fetch markerがcompletionまでidempotentである契約を検証する.

    同一metadata targetを連続でpending化して成功記録後に再びpending化する.
    2回目はstateを変えず成功後はattempt countを増やしてpendingになることを確認する.

    Returns:
        None: fetch pending lifecycleとattempt countを検証して完了する.
    """
    repo = _repo()
    target = BeatmapFetchTarget.metadata_by_beatmap_id(2_000)

    first = await repo.try_mark_fetch_pending(target, now=_NOW)
    duplicate = await repo.try_mark_fetch_pending(target, now=_NOW + timedelta(seconds=1))
    state = await repo.get_fetch_state(target)

    assert first is True
    assert duplicate is False
    assert state is not None
    assert state.status is BeatmapFetchState.PENDING_FETCH
    assert state.attempt_count == 1
    assert state.pending_since == _NOW

    await repo.mark_fetch_succeeded(target, now=_NOW + timedelta(seconds=2))
    second_pending = await repo.try_mark_fetch_pending(target, now=_NOW + timedelta(seconds=3))

    assert second_pending is True
    refreshed_state = await repo.get_fetch_state(target)
    assert refreshed_state is not None
    assert refreshed_state.status is BeatmapFetchState.PENDING_FETCH
    assert refreshed_state.attempt_count == 2


async def test_failed_fetch_state_is_observable() -> None:
    """Failed fetchがreasonとattempt timestampを観測可能に保存する契約を検証する.

    file targetをpending化してtimeout reasonを持つfailed stateへ遷移させる.
    get fetch stateがFAILED statusとreason/時刻を返すことを確認する.

    Returns:
        None: fetch failureのobservable stateを検証して完了する.
    """
    repo = _repo()
    target = BeatmapFetchTarget.file_by_beatmap_id(2_000)

    _ = await repo.try_mark_fetch_pending(target, now=_NOW)
    await repo.mark_fetch_failed(target, reason="timeout", now=_NOW + timedelta(seconds=5))

    state = await repo.get_fetch_state(target)
    assert state is not None
    assert state.status is BeatmapFetchState.FAILED
    assert state.last_error == "timeout"
    assert state.last_attempted_at == _NOW + timedelta(seconds=5)


# ---------------------------------------------------------------------------
# Filename-within-beatmapset lookup (task 1.2)
# ---------------------------------------------------------------------------


async def test_resolves_beatmap_by_exact_filename_in_beatmapset() -> None:
    """Exact original filenameが同じBeatmapSet内のBeatmapを返す契約を検証する.

    attachmentのoriginal filenameを持つBeatmap snapshotを保存して同じset/filenameで検索する.
    attachmentを所有するBeatmapがIDを保って返ることを確認する.

    Returns:
        None: exact filename lookupのmatching結果を検証して完了する.
    """
    repo = _repo()
    attachment = replace(_make_attachment(beatmap_id=2_000), original_filename="my_map.osu")
    beatmap = _make_beatmap(file_attachment=attachment)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    result = await repo.get_beatmap_by_filename_in_beatmapset(1_000, "my_map.osu")

    assert result is not None
    assert result.id == 2_000


async def test_filename_lookup_returns_none_when_no_match_in_set() -> None:
    """set内に一致filenameがないlookupがNoneを返す契約を検証する.

    real.osu attachmentを持つBeatmapSetへother.osuを指定して検索する.
    同set内にexact matchがないためresultがNoneになることを確認する.

    Returns:
        None: unknown filenameのempty lookup結果を検証して完了する.
    """
    repo = _repo()
    attachment = replace(_make_attachment(beatmap_id=2_000), original_filename="real.osu")
    beatmap = _make_beatmap(file_attachment=attachment)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    result = await repo.get_beatmap_by_filename_in_beatmapset(1_000, "other.osu")

    assert result is None


async def test_filename_lookup_returns_none_when_set_does_not_exist() -> None:
    """存在しないBeatmapSetのfilename lookupがNoneを返す契約を検証する.

    snapshotを保存しないrepositoryへ未登録set IDと任意filenameを指定する.
    lookupがexceptionを送出せずNoneを返すことを確認する.

    Returns:
        None: unknown BeatmapSetのempty lookup結果を検証して完了する.
    """
    repo = _repo()

    result = await repo.get_beatmap_by_filename_in_beatmapset(999, "anything.osu")

    assert result is None


async def test_filename_lookup_returns_none_for_partial_filename_match() -> None:
    """Partial filename fragmentがBeatmapを解決しない契約を検証する.

    my_map.osu attachmentを持つBeatmapSetへbasename/extension/部分文字列を指定して検索する.
    original filenameの完全一致だけを許可し各partial lookupがNoneになることを確認する.

    Returns:
        None: exact filename matching制約を検証して完了する.
    """
    repo = _repo()
    attachment = replace(_make_attachment(beatmap_id=2_000), original_filename="my_map.osu")
    beatmap = _make_beatmap(file_attachment=attachment)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, "my_map") is None
    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, ".osu") is None
    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, "map.osu") is None


async def test_filename_lookup_scoped_to_beatmapset() -> None:
    """Filename lookupが一致するBeatmapSetの内部だけを検索する契約を検証する.

    shared.osuを持つsetとother.osuだけを持つ別setを保存してshared.osuを両setで検索する.
    filenameが他setに存在しても対象set内にない場合はNoneになることを確認する.

    Returns:
        None: BeatmapSetでscopeされたfilename lookupを検証して完了する.
    """
    repo = _repo()

    # Beatmapset 1000: beatmap 2000 with "shared.osu"
    attachment_a = replace(_make_attachment(beatmap_id=2_000), original_filename="shared.osu")
    beatmap_a = _make_beatmap(beatmap_id=2_000, beatmapset_id=1_000, file_attachment=attachment_a)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap_a))

    # Beatmapset 2000: beatmap 3000 with "other.osu" (no "shared.osu" here)
    attachment_b = replace(_make_attachment(beatmap_id=3_000), original_filename="other.osu")
    beatmap_b = _make_beatmap(
        beatmap_id=3_000,
        beatmapset_id=2_000,
        checksum_md5=_OTHER_CHECKSUM,
        file_attachment=attachment_b,
    )
    await repo.save_beatmapset_snapshot(replace(_make_beatmapset(beatmap_b), id=2_000))

    # "shared.osu" exists in set 1000 but NOT in set 2000
    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, "shared.osu") is not None
    assert await repo.get_beatmap_by_filename_in_beatmapset(2_000, "shared.osu") is None


async def test_filename_lookup_beatmap_without_attachment_returns_none() -> None:
    """File attachmentのないBeatmapがfilenameで解決されない契約を検証する.

    attachmentなしのBeatmap snapshotを保存して予想filenameで検索する.
    file metadataがないためlookupがNoneを返すことを確認する.

    Returns:
        None: attachment不在時のfilename lookup結果を検証して完了する.
    """
    repo = _repo()
    beatmap = _make_beatmap()  # no file_attachment
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    result = await repo.get_beatmap_by_filename_in_beatmapset(1_000, "2000.osu")

    assert result is None
