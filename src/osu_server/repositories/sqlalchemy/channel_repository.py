"""SQLAlchemyChannelRepository — async database-backed channel repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: TC002

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelModel,
    ChannelRoleOverrideModel,
)


class SQLAlchemyChannelRepository:
    """SQLAlchemy implementation of the ChannelRepository Protocol.

    Uses ``async_sessionmaker`` for database access.  Each method opens
    its own session to keep transactions short.
    """

    _session_factory: async_sessionmaker[AsyncSession]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, channel: Channel) -> Channel:
        """Persist a new channel and return it with a generated id.

        Raises ``ValueError`` if ``name`` already exists.
        """
        async with self._session_factory() as session:
            stmt = select(ChannelModel).where(ChannelModel.name == channel.name)
            existing = (await session.execute(stmt)).scalar_one_or_none()
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
            session.add(model)
            await session.commit()
            await session.refresh(model)

            return self._to_domain(model)

    async def get_by_name(self, name: str) -> Channel | None:
        """Return the channel with *name*, or ``None`` if not found."""
        async with self._session_factory() as session:
            stmt = select(ChannelModel).where(ChannelModel.name == name)
            model = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_domain(model) if model is not None else None

    async def get_all(self) -> list[Channel]:
        """Return all PUBLIC channels."""
        async with self._session_factory() as session:
            stmt = select(ChannelModel).where(
                ChannelModel.channel_type == ChannelType.PUBLIC.value
            )
            models = (await session.execute(stmt)).scalars().all()
            return [self._to_domain(m) for m in models]

    async def get_auto_join(self) -> list[Channel]:
        """Return all channels with ``auto_join=True``."""
        async with self._session_factory() as session:
            stmt = select(ChannelModel).where(ChannelModel.auto_join.is_(True))
            models = (await session.execute(stmt)).scalars().all()
            return [self._to_domain(m) for m in models]

    async def update(self, channel: Channel) -> Channel:
        """Update an existing channel and return the updated entity.

        Raises ``ValueError`` if the channel does not exist.
        """
        async with self._session_factory() as session:
            model = await session.get(ChannelModel, channel.id)
            if model is None:
                msg = f"channel not found: id={channel.id}"
                raise ValueError(msg)

            model.name = channel.name
            model.topic = channel.topic
            model.channel_type = channel.channel_type.value
            model.auto_join = channel.auto_join
            model.rate_limit_messages = channel.rate_limit_messages
            model.rate_limit_window = channel.rate_limit_window

            await session.commit()
            await session.refresh(model)

            return self._to_domain(model)

    async def delete(self, channel_id: int) -> None:
        """Delete the channel with *channel_id*.  No-op if not found."""
        async with self._session_factory() as session:
            model = await session.get(ChannelModel, channel_id)
            if model is not None:
                await session.delete(model)
                await session.commit()

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """Return all role overrides for a single channel."""
        async with self._session_factory() as session:
            stmt = select(ChannelRoleOverrideModel).where(
                ChannelRoleOverrideModel.channel_id == channel_id
            )
            models = (await session.execute(stmt)).scalars().all()
            return [self._override_to_domain(m) for m in models]

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """Return role overrides for multiple channels, keyed by channel_id."""
        if not channel_ids:
            return {}

        result: dict[int, list[ChannelRoleOverride]] = {cid: [] for cid in channel_ids}
        async with self._session_factory() as session:
            stmt = select(ChannelRoleOverrideModel).where(
                ChannelRoleOverrideModel.channel_id.in_(channel_ids)
            )
            models = (await session.execute(stmt)).scalars().all()
            for m in models:
                result[m.channel_id].append(self._override_to_domain(m))
        return result

    @staticmethod
    def _to_domain(model: ChannelModel) -> Channel:
        """Map a SQLAlchemy ChannelModel to a domain Channel."""
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

    @staticmethod
    def _override_to_domain(model: ChannelRoleOverrideModel) -> ChannelRoleOverride:
        """Map a SQLAlchemy ChannelRoleOverrideModel to a domain ChannelRoleOverride."""
        return ChannelRoleOverride(
            channel_id=model.channel_id,
            role_id=model.role_id,
            can_read=model.can_read,
            can_write=model.can_write,
        )
