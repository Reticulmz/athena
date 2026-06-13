"""SQLAlchemy query-side beatmap repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    attachment_to_domain,
    beatmap_to_domain,
    beatmapset_to_domain,
    fetch_state_to_domain,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
    )


class SQLAlchemyBeatmapQueryRepository:
    """Read-only beatmap repository backed by short SQLAlchemy sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        async with self._session_factory() as session:
            model = await session.get(BeatmapModel, beatmap_id)
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session,
                beatmap_id=beatmap_id,
            )
            return beatmap_to_domain(model, attachment)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        async with self._session_factory() as session:
            model = await session.get(BeatmapSetModel, beatmapset_id)
            if not isinstance(model, BeatmapSetModel):
                return None
            beatmap_models = await self._get_beatmap_models_for_set(
                session,
                beatmapset_id=beatmapset_id,
            )
            beatmaps = [
                beatmap_to_domain(
                    beatmap_model,
                    await self._get_current_file_attachment_model(
                        session,
                        beatmap_id=beatmap_model.id,
                    ),
                )
                for beatmap_model in beatmap_models
            ]
            return beatmapset_to_domain(model, tuple(beatmaps))

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(BeatmapModel).where(BeatmapModel.checksum_md5 == checksum_md5)
                )
            ).scalar_one_or_none()
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session,
                beatmap_id=model.id,
            )
            return beatmap_to_domain(model, attachment)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(BeatmapModel)
                    .join(
                        BeatmapFileAttachmentModel,
                        BeatmapFileAttachmentModel.beatmap_id == BeatmapModel.id,
                    )
                    .where(
                        BeatmapModel.beatmapset_id == beatmapset_id,
                        BeatmapFileAttachmentModel.original_filename == original_filename,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session,
                beatmap_id=model.id,
            )
            return beatmap_to_domain(model, attachment)

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        async with self._session_factory() as session:
            model = await self._get_current_file_attachment_model(
                session,
                beatmap_id=beatmap_id,
            )
            return attachment_to_domain(model) if model is not None else None

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(BeatmapFetchStateModel).where(
                        BeatmapFetchStateModel.target_type == target.target_type,
                        BeatmapFetchStateModel.target_key == target.target_key,
                    )
                )
            ).scalar_one_or_none()
            return (
                fetch_state_to_domain(model) if isinstance(model, BeatmapFetchStateModel) else None
            )

    @staticmethod
    async def _get_beatmap_models_for_set(
        session: AsyncSession,
        *,
        beatmapset_id: int,
    ) -> list[BeatmapModel]:
        result = await session.execute(
            select(BeatmapModel).where(BeatmapModel.beatmapset_id == beatmapset_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _get_current_file_attachment_model(
        session: AsyncSession,
        *,
        beatmap_id: int,
    ) -> BeatmapFileAttachmentModel | None:
        model = (
            await session.execute(
                select(BeatmapFileAttachmentModel)
                .where(BeatmapFileAttachmentModel.beatmap_id == beatmap_id)
                .order_by(BeatmapFileAttachmentModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None
