"""SQLAlchemy query-side channel repository."""

from __future__ import annotations

from sqlalchemy import select

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelModel,
    ChannelRoleOverrideModel,
)
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    channel_override_to_domain,
    channel_to_domain,
)


class SQLAlchemyChannelQueryRepository:
    """Read-only channel repository backed by short SQLAlchemy sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def get_by_name(self, name: str) -> Channel | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(select(ChannelModel).where(ChannelModel.name == name))
            ).scalar_one_or_none()
            return channel_to_domain(model) if isinstance(model, ChannelModel) else None

    async def get_all(self) -> list[Channel]:
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelModel).where(
                            ChannelModel.channel_type == ChannelType.PUBLIC.value
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [channel_to_domain(model) for model in models]

    async def get_auto_join(self) -> list[Channel]:
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelModel).where(ChannelModel.auto_join.is_(True))
                    )
                )
                .scalars()
                .all()
            )
            return [channel_to_domain(model) for model in models]

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelRoleOverrideModel).where(
                            ChannelRoleOverrideModel.channel_id == channel_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [channel_override_to_domain(model) for model in models]

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        if not channel_ids:
            return {}

        result: dict[int, list[ChannelRoleOverride]] = {
            channel_id: [] for channel_id in channel_ids
        }
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelRoleOverrideModel).where(
                            ChannelRoleOverrideModel.channel_id.in_(channel_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for model in models:
                result[model.channel_id].append(channel_override_to_domain(model))
        return result
