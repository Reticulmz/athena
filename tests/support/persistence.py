"""Test helpers for seeding command-side in-memory persistence."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapFetchState
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.repositories.memory.commands.channels import InMemoryChannelCommandRepository
from osu_server.repositories.memory.commands.roles import InMemoryRoleCommandRepository
from tests.support.app import resolve_dependency

if TYPE_CHECKING:
    from datetime import datetime

    from starlette.applications import Starlette

    from osu_server.domain.beatmaps import BeatmapFetchTarget, BeatmapFileAttachment, BeatmapSet
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.domain.identity.roles import Role
    from osu_server.domain.identity.users import User


async def seed_role(app: Starlette, role: Role) -> None:
    """Seed a role through the command Unit of Work boundary."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        roles = uow.roles
        assert isinstance(roles, InMemoryRoleCommandRepository)
        roles.add_role(role)
        await uow.commit()


def seed_role_sync(app: Starlette, role: Role) -> None:
    """Synchronous wrapper for TestClient-based tests."""
    asyncio.run(seed_role(app, role))


async def seed_user(app: Starlette, user: User) -> User:
    """Create a user through the command Unit of Work boundary."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        created = await uow.users.create(user)
        await uow.commit()
        return created


async def seed_channel(app: Starlette, channel: Channel) -> Channel:
    """Create a channel through the command Unit of Work boundary."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        created = await uow.channels.create(channel)
        await uow.commit()
        return created


async def seed_channel_override(app: Starlette, override: ChannelRoleOverride) -> None:
    """Seed a channel role override for command-side ACL checks."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        channels = uow.channels
        assert isinstance(channels, InMemoryChannelCommandRepository)
        channels.seed_override(override)
        await uow.commit()


async def seed_beatmapset(app: Starlette, beatmapset: BeatmapSet) -> None:
    """Save a beatmapset snapshot through the command Unit of Work boundary."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(beatmapset)
        await uow.commit()


async def attach_beatmap_file(
    app: Starlette,
    attachment: BeatmapFileAttachment,
) -> BeatmapFileAttachment:
    """Attach an osu file snapshot through the command Unit of Work boundary."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        created = await uow.beatmaps.attach_osu_file(attachment)
        await uow.commit()
        return created


async def seed_beatmap_fetch_state(
    app: Starlette,
    target: BeatmapFetchTarget,
    status: BeatmapFetchState,
    now: datetime,
    *,
    failed_reason: str = "test metadata failure",
) -> None:
    """Seed a beatmap fetch state through the command Unit of Work boundary."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        if status is BeatmapFetchState.PENDING_FETCH:
            _ = await uow.beatmaps.try_mark_fetch_pending(target, now)
        elif status is BeatmapFetchState.FAILED:
            await uow.beatmaps.mark_fetch_failed(target, failed_reason, now)
        else:
            await uow.beatmaps.mark_fetch_succeeded(target, now)
        await uow.commit()
