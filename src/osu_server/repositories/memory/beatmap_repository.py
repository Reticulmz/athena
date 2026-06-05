from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.beatmap import BeatmapFetchState, BeatmapFileState
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchRecord,
    BeatmapFetchTarget,
    BeatmapNotFoundError,
    DuplicateBeatmapChecksumError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmap import (
        Beatmap,
        BeatmapFileAttachment,
        BeatmapSet,
        LocalBeatmapStatus,
    )


class InMemoryBeatmapRepository:
    def __init__(self) -> None:
        self._beatmapsets: dict[int, BeatmapSet] = {}
        self._beatmaps: dict[int, Beatmap] = {}
        self._beatmap_ids_by_checksum: dict[str, int] = {}
        self._attachments_by_key: dict[tuple[int, str], BeatmapFileAttachment] = {}
        self._attachment_keys_by_beatmap_id: dict[int, list[tuple[int, str]]] = {}
        self._fetch_states: dict[BeatmapFetchTarget, BeatmapFetchRecord] = {}

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        return self._beatmaps.get(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        return self._beatmapsets.get(beatmapset_id)

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        beatmap_id = self._beatmap_ids_by_checksum.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self._beatmaps.get(beatmap_id)

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        self._check_checksum_conflicts(snapshot)

        stored_beatmaps = tuple(
            self._merge_beatmap_snapshot(beatmap) for beatmap in snapshot.beatmaps
        )
        for beatmap in stored_beatmaps:
            self._store_beatmap(beatmap)

        self._beatmapsets[snapshot.id] = replace(snapshot, beatmaps=stored_beatmaps)

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        existing = self._require_beatmap(beatmap_id)
        updated = replace(existing, local_status_override=status)
        self._store_beatmap(updated)
        self._refresh_beatmapset_child(updated)
        return updated

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        keys = self._attachment_keys_by_beatmap_id.get(beatmap_id)
        if not keys:
            return None
        return self._attachments_by_key[keys[-1]]

    async def attach_osu_file(self, attachment: BeatmapFileAttachment) -> BeatmapFileAttachment:
        existing_beatmap = self._require_beatmap(attachment.beatmap_id)
        key = (attachment.beatmap_id, attachment.checksum_md5)
        existing_attachment = self._attachments_by_key.get(key)
        if existing_attachment is not None:
            return existing_attachment

        self._attachments_by_key[key] = attachment
        self._attachment_keys_by_beatmap_id.setdefault(attachment.beatmap_id, []).append(key)
        updated_beatmap = replace(
            existing_beatmap,
            file_state=BeatmapFileState.AVAILABLE,
            file_attachment=attachment,
        )
        self._store_beatmap(updated_beatmap)
        self._refresh_beatmapset_child(updated_beatmap)
        return attachment

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        return self._fetch_states.get(target)

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        existing = self._fetch_states.get(target)
        if existing is not None and existing.status is BeatmapFetchState.PENDING_FETCH:
            return False

        attempt_count = 1 if existing is None else existing.attempt_count + 1
        self._fetch_states[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.PENDING_FETCH,
            attempt_count=attempt_count,
            last_error=None,
            pending_since=now,
            last_attempted_at=now,
        )
        return True

    async def mark_fetch_succeeded(self, target: BeatmapFetchTarget, now: datetime) -> None:
        existing = self._fetch_states.get(target)
        self._fetch_states[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.FRESH,
            attempt_count=0 if existing is None else existing.attempt_count,
            last_error=None,
            pending_since=None,
            last_attempted_at=now,
        )

    async def mark_fetch_failed(
        self, target: BeatmapFetchTarget, reason: str, now: datetime
    ) -> None:
        existing = self._fetch_states.get(target)
        self._fetch_states[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.FAILED,
            attempt_count=0 if existing is None else existing.attempt_count,
            last_error=reason,
            pending_since=None,
            last_attempted_at=now,
        )

    def _check_checksum_conflicts(self, snapshot: BeatmapSet) -> None:
        incoming_beatmap_ids_by_checksum: dict[str, int] = {}
        for beatmap in snapshot.beatmaps:
            incoming_beatmap_id = incoming_beatmap_ids_by_checksum.get(beatmap.checksum_md5)
            if incoming_beatmap_id is not None and incoming_beatmap_id != beatmap.id:
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=beatmap.checksum_md5,
                    existing_beatmap_id=incoming_beatmap_id,
                )
            incoming_beatmap_ids_by_checksum[beatmap.checksum_md5] = beatmap.id

            existing_beatmap_id = self._beatmap_ids_by_checksum.get(beatmap.checksum_md5)
            if existing_beatmap_id is not None and existing_beatmap_id != beatmap.id:
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=beatmap.checksum_md5,
                    existing_beatmap_id=existing_beatmap_id,
                )

    def _merge_beatmap_snapshot(self, beatmap: Beatmap) -> Beatmap:
        existing = self._beatmaps.get(beatmap.id)
        if existing is None:
            return beatmap

        local_status_override = existing.local_status_override or beatmap.local_status_override
        file_attachment = existing.file_attachment or beatmap.file_attachment
        file_state = (
            BeatmapFileState.AVAILABLE if file_attachment is not None else beatmap.file_state
        )

        return replace(
            beatmap,
            local_status_override=local_status_override,
            file_state=file_state,
            file_attachment=file_attachment,
        )

    def _store_beatmap(self, beatmap: Beatmap) -> None:
        existing = self._beatmaps.get(beatmap.id)
        if existing is not None and existing.checksum_md5 != beatmap.checksum_md5:
            _ = self._beatmap_ids_by_checksum.pop(existing.checksum_md5, None)

        self._beatmaps[beatmap.id] = beatmap
        self._beatmap_ids_by_checksum[beatmap.checksum_md5] = beatmap.id

    def _refresh_beatmapset_child(self, beatmap: Beatmap) -> None:
        beatmapset = self._beatmapsets.get(beatmap.beatmapset_id)
        if beatmapset is None:
            return
        self._beatmapsets[beatmapset.id] = replace(
            beatmapset,
            beatmaps=tuple(
                beatmap if existing.id == beatmap.id else existing
                for existing in beatmapset.beatmaps
            ),
        )

    def _require_beatmap(self, beatmap_id: int) -> Beatmap:
        beatmap = self._beatmaps.get(beatmap_id)
        if beatmap is None:
            raise BeatmapNotFoundError(beatmap_id)
        return beatmap
