"""SQLAlchemy command-side channel repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelModel,
    ChannelRoleOverrideModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyChannelCommandRepository:
    """Channel command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def create(self, channel: Channel) -> Channel:
        existing = (
            await self._session.execute(
                select(ChannelModel).where(ChannelModel.name == channel.name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            msg = f"channel name already exists: {channel.name}"
            raise ValueError(msg)

        model = ChannelModel(
            name=channel.name,
            topic=channel.topic,
            channel_type=channel.channel_type.value,
            auto_join=channel.auto_join,
            rate_limit_messages=channel.rate_limit_messages,
            rate_limit_window=channel.rate_limit_window,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _channel_to_domain(model)

    async def get_by_name(self, name: str) -> Channel | None:
        model = (
            await self._session.execute(select(ChannelModel).where(ChannelModel.name == name))
        ).scalar_one_or_none()
        return _channel_to_domain(model) if isinstance(model, ChannelModel) else None

    async def update(self, channel: Channel) -> Channel:
        model = await self._session.get(ChannelModel, channel.id)
        if model is None:
            msg = f"channel not found: id={channel.id}"
            raise ValueError(msg)
        assert isinstance(model, ChannelModel)

        model.name = channel.name
        model.topic = channel.topic
        model.channel_type = channel.channel_type.value
        model.auto_join = channel.auto_join
        model.rate_limit_messages = channel.rate_limit_messages
        model.rate_limit_window = channel.rate_limit_window
        await self._session.flush()
        await self._session.refresh(model)
        return _channel_to_domain(model)

    async def delete(self, channel_id: int) -> None:
        model = await self._session.get(ChannelModel, channel_id)
        if model is not None:
            assert isinstance(model, ChannelModel)
            await self._session.delete(model)
            await self._session.flush()

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        models = (
            (
                await self._session.execute(
                    select(ChannelRoleOverrideModel).where(
                        ChannelRoleOverrideModel.channel_id == channel_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return [_override_to_domain(model) for model in models]

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        if not channel_ids:
            return {}

        result: dict[int, list[ChannelRoleOverride]] = {
            channel_id: [] for channel_id in channel_ids
        }
        models = (
            (
                await self._session.execute(
                    select(ChannelRoleOverrideModel).where(
                        ChannelRoleOverrideModel.channel_id.in_(channel_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for model in models:
            result[model.channel_id].append(_override_to_domain(model))
        return result


def _channel_to_domain(model: ChannelModel) -> Channel:
    return Channel(
        id=model.id,
        name=model.name,
        topic=model.topic,
        channel_type=ChannelType(model.channel_type),
        auto_join=model.auto_join,
        rate_limit_messages=model.rate_limit_messages,
        rate_limit_window=model.rate_limit_window,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _override_to_domain(model: ChannelRoleOverrideModel) -> ChannelRoleOverride:
    return ChannelRoleOverride(
        channel_id=model.channel_id,
        role_id=model.role_id,
        can_read=model.can_read,
        can_write=model.can_write,
    )
