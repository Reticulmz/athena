"""command-side in-memory persistenceをseedするtest helperを提供する."""

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
    """Command Unit of Work boundaryを通じてroleをseedする.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        role (Role): command stateへ追加するrole.

    Returns:
        None: roleをcommitし, 呼び出し側へ値を返さずに完了する.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        roles = uow.roles
        assert isinstance(roles, InMemoryRoleCommandRepository)
        roles.add_role(role)
        await uow.commit()


def seed_role_sync(app: Starlette, role: Role) -> None:
    """同期TestClient testからroleをseedする.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        role (Role): command stateへ追加するrole.

    Returns:
        None: 非同期seedを完了し, 呼び出し側へ値を返さずに完了する.

    Notes:
        実行中のevent loopを持たない同期testからだけ利用する.
    """
    asyncio.run(seed_role(app, role))


async def seed_user(app: Starlette, user: User) -> User:
    """Command Unit of Work boundaryを通じてuserを作成する.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        user (User): command stateへ保存するuser.

    Returns:
        User: repositoryが作成してcommitしたuser.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        created = await uow.users.create(user)
        await uow.commit()
        return created


async def seed_channel(app: Starlette, channel: Channel) -> Channel:
    """Command Unit of Work boundaryを通じてchannelを作成する.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        channel (Channel): command stateへ保存するchannel.

    Returns:
        Channel: repositoryが作成してcommitしたchannel.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        created = await uow.channels.create(channel)
        await uow.commit()
        return created


async def seed_channel_override(app: Starlette, override: ChannelRoleOverride) -> None:
    """command-side ACL check用のchannel role overrideをseedする.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        override (ChannelRoleOverride): channel command repositoryへ設定するrole override.

    Returns:
        None: overrideをcommitし, 呼び出し側へ値を返さずに完了する.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        channels = uow.channels
        assert isinstance(channels, InMemoryChannelCommandRepository)
        channels.seed_override(override)
        await uow.commit()


async def seed_beatmapset(app: Starlette, beatmapset: BeatmapSet) -> None:
    """Command Unit of Work boundaryを通じてbeatmapset snapshotを保存する.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        beatmapset (BeatmapSet): command stateへ保存するbeatmapset snapshot.

    Returns:
        None: snapshotをcommitし, 呼び出し側へ値を返さずに完了する.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(beatmapset)
        await uow.commit()


async def attach_beatmap_file(
    app: Starlette,
    attachment: BeatmapFileAttachment,
) -> BeatmapFileAttachment:
    """Command Unit of Work boundaryを通じてosu file snapshotをattachする.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        attachment (BeatmapFileAttachment): beatmapへattachするosu file snapshot.

    Returns:
        BeatmapFileAttachment: repositoryが保存してcommitしたattachment.
    """
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
    """Command Unit of Work boundaryを通じてbeatmap fetch stateをseedする.

    Args:
        app (Starlette): in-memory runtime provider付きapplication.
        target (BeatmapFetchTarget): stateを記録するbeatmap fetch target.
        status (BeatmapFetchState): seedするpending, failed, またはsucceeded状態.
        now (datetime): state transitionを記録する時刻.
        failed_reason (str): failed状態で保存するdiagnostic reason.

    Returns:
        None: statusに対応するmutationをcommitし, 呼び出し側へ値を返さずに完了する.

    Notes:
        failed_reasonはstatusがFAILEDの場合だけrepositoryへ渡される.
    """
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        if status is BeatmapFetchState.PENDING_FETCH:
            _ = await uow.beatmaps.try_mark_fetch_pending(target, now)
        elif status is BeatmapFetchState.FAILED:
            await uow.beatmaps.mark_fetch_failed(target, failed_reason, now)
        else:
            await uow.beatmaps.mark_fetch_succeeded(target, now)
        await uow.commit()
