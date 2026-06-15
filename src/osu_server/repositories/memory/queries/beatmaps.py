"""In-memory query-side beatmap repository adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
    )
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryBeatmapQueryRepository:
    """Read-only beatmap repository that reads committed memory state."""

    _factory: InMemoryUnitOfWorkFactory

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory = uow_factory

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        state = self._factory.snapshot()
        return state.beatmaps_by_id.get(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        state = self._factory.snapshot()
        return state.beatmapsets_by_id.get(beatmapset_id)

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        state = self._factory.snapshot()
        beatmap_id = state.beatmap_id_by_checksum.get(checksum_md5)
        if beatmap_id is None:
            return None
        return state.beatmaps_by_id.get(beatmap_id)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        state = self._factory.snapshot()
        beatmapset = state.beatmapsets_by_id.get(beatmapset_id)
        if beatmapset is None:
            return None
        for beatmap in beatmapset.beatmaps:
            attachment = beatmap.file_attachment
            if attachment is not None and attachment.original_filename == original_filename:
                return beatmap
        return None

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        state = self._factory.snapshot()
        keys = state.attachment_keys_by_beatmap_id.get(beatmap_id)
        if not keys:
            return None
        return state.attachments_by_key[keys[-1]]

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        state = self._factory.snapshot()
        return state.fetch_states_by_target.get(target)
