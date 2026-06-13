"""ChannelService — チャンネル CRUD、メンバーシップ管理、アクセス制御。

パケット構築・配信はトランスポート層の責務。本サービスは構造化された結果を
返し、呼び出し元が S2C パケットの構築と PacketQueue への enqueue を行う。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.authorization import Privileges, has_privilege

if TYPE_CHECKING:
    from osu_server.domain.channel import Channel, ChannelRoleOverride
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )
    from osu_server.repositories.interfaces.channel_repository import ChannelRepository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ChannelService:
    """チャンネル CRUD、メンバーシップ管理、アクセス制御。

    アクセス制御は Discord 方式のロール別 ACL で実施:
    1. BYPASS_CHANNEL_ACL → 常に許可 (ADMIN も has_privilege 経由でバイパス)
    2. channel_role_overrides を照合し、ユーザーのロール群に can_read/can_write がある場合に許可
    3. オーバーライドなし → fail-closed (アクセス不可)
    """

    _channel_repo: ChannelRepository
    _channel_state: ChannelStateStore

    def __init__(
        self,
        *,
        channel_repo: ChannelRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        self._channel_repo = channel_repo
        self._channel_state = channel_state

    # ── CRUD ─────────────────────────────────────────────────────────

    async def create_channel(self, channel: Channel) -> Channel:
        """チャンネルを作成する。名前重複時は ValueError。"""
        return await self._channel_repo.create(channel)

    async def get_channel(self, name: str) -> Channel | None:
        """名前でチャンネルを取得する。"""
        return await self._channel_repo.get_by_name(name)

    async def get_all_channels(self) -> list[Channel]:
        """全 PUBLIC チャンネルを取得する。"""
        return await self._channel_repo.get_all()

    async def update_channel(self, channel: Channel) -> Channel:
        """チャンネルを更新する。存在しない場合は ValueError。"""
        return await self._channel_repo.update(channel)

    async def delete_channel(self, channel_id: int) -> None:
        """チャンネルを削除する。存在しない場合は no-op。"""
        await self._channel_repo.delete(channel_id)

    # ── Membership ───────────────────────────────────────────────────

    async def join(
        self,
        *,
        user_id: int,
        user_privileges: int,
        user_role_ids: list[int],
        channel_name: str,
    ) -> bool:
        """チャンネルに参加する。

        Returns:
            True: 参加成功(呼び出し元が CHANNEL_JOIN_SUCCESS を送信)
            False: 権限不足 / チャンネル不存在(呼び出し元が CHANNEL_REVOKED を送信)

        冪等: 既に参加済みなら何もせず True を返す。
        """
        # Check if already a member (idempotent)
        if await self._channel_state.is_member(channel_name, user_id):
            logger.debug("join_idempotent", user_id=user_id, channel=channel_name)
            return True

        # Load channel
        channel = await self._channel_repo.get_by_name(channel_name)
        if channel is None:
            logger.warning(
                "join_failed",
                user_id=user_id,
                channel=channel_name,
                reason="channel_not_found",
            )
            return False

        # ACL check: BYPASS_CHANNEL_ACL or role-based override (can_read)
        if not has_privilege(user_privileges, Privileges.BYPASS_CHANNEL_ACL):
            overrides = await self._channel_repo.get_overrides_for_channel(channel.id)
            if not self._check_acl(overrides, user_role_ids, permission="read"):
                logger.warning(
                    "join_failed",
                    user_id=user_id,
                    channel=channel_name,
                    reason="permission_denied",
                )
                return False

        # Add member
        await self._channel_state.add_member(channel_name, user_id)
        logger.info("join_success", user_id=user_id, channel=channel_name)
        return True

    async def leave(self, *, user_id: int, channel_name: str) -> None:
        """チャンネルから離脱する。

        呼び出し元が CHANNEL_REVOKED を送信する。
        """
        await self._channel_state.remove_member(channel_name, user_id)
        logger.info("leave", user_id=user_id, channel=channel_name)

    # ── Message delivery ─────────────────────────────────────────────

    async def get_delivery_targets(
        self,
        *,
        sender_id: int,
        user_privileges: int,
        user_role_ids: list[int],
        channel_name: str,
    ) -> set[int] | None:
        """チャンネルメッセージの配信先メンバー一覧を返す。

        membership + 書き込み権限を検証し、送信者を除いたメンバー集合を返す。

        Returns:
            set[int]: 配信先ユーザー ID 集合(sender 除外済み)
            None: 未参加 / 権限不足 / チャンネル不存在
        """
        # Membership check
        if not await self._channel_state.is_member(channel_name, sender_id):
            logger.warning(
                "deliver_rejected",
                sender_id=sender_id,
                channel=channel_name,
                reason="not_a_member",
            )
            return None

        # Write ACL check: BYPASS_CHANNEL_ACL or role-based override (can_write)
        if not has_privilege(user_privileges, Privileges.BYPASS_CHANNEL_ACL):
            channel = await self._channel_repo.get_by_name(channel_name)
            if channel is None:
                logger.warning(
                    "deliver_rejected",
                    sender_id=sender_id,
                    channel=channel_name,
                    reason="channel_not_found",
                )
                return None

            overrides = await self._channel_repo.get_overrides_for_channel(channel.id)
            if not self._check_acl(overrides, user_role_ids, permission="write"):
                logger.warning(
                    "deliver_rejected",
                    sender_id=sender_id,
                    channel=channel_name,
                    reason="write_permission_denied",
                )
                return None

        # Return members excluding sender
        members = await self._channel_state.get_members(channel_name)
        targets = members - {sender_id}
        logger.info(
            "delivery_targets_resolved",
            sender_id=sender_id,
            channel=channel_name,
            recipient_count=len(targets),
        )
        return targets

    # ── Login channel lists ──────────────────────────────────────────

    async def get_visible_channels(
        self,
        *,
        user_privileges: int,
        user_role_ids: list[int],
    ) -> list[tuple[Channel, int]]:
        """ユーザーが閲覧可能なチャンネル一覧を member_count 付きで返す。

        BYPASS_CHANNEL_ACL / ADMIN → 全チャンネル返却。
        それ以外 → ロール照合で can_read=True のチャンネルのみ。
        """
        all_channels = await self._channel_repo.get_all()
        return await self._filter_channels_with_count(all_channels, user_privileges, user_role_ids)

    async def get_autojoin_channels(
        self,
        *,
        user_privileges: int,
        user_role_ids: list[int],
    ) -> list[tuple[Channel, int]]:
        """auto_join=True かつユーザーが閲覧可能なチャンネル一覧を返す。"""
        autojoin_channels = await self._channel_repo.get_auto_join()
        return await self._filter_channels_with_count(
            autojoin_channels, user_privileges, user_role_ids
        )

    # ── Private helpers ──────────────────────────────────────────────

    async def _filter_channels_with_count(
        self,
        channels: list[Channel],
        user_privileges: int,
        user_role_ids: list[int],
    ) -> list[tuple[Channel, int]]:
        """チャンネルリストを ACL フィルタし、member_count を付与する。"""
        bypass = has_privilege(user_privileges, Privileges.BYPASS_CHANNEL_ACL)

        if bypass:
            visible = channels
        else:
            # Batch-fetch overrides for all channels
            channel_ids = [ch.id for ch in channels]
            overrides_map = await self._channel_repo.get_overrides_for_channels(channel_ids)
            visible = [
                ch
                for ch in channels
                if self._check_acl(
                    overrides_map.get(ch.id, []),
                    user_role_ids,
                    permission="read",
                )
            ]

        result: list[tuple[Channel, int]] = []
        for ch in visible:
            count = await self._channel_state.get_member_count(ch.name)
            result.append((ch, count))
        return result

    @staticmethod
    def _check_acl(
        overrides: list[ChannelRoleOverride],
        user_role_ids: list[int],
        *,
        permission: str,
    ) -> bool:
        """ロール別オーバーライドでアクセス権を判定する (fail-closed)。"""
        if not overrides:
            return False  # fail-closed

        user_role_set = set(user_role_ids)
        for override in overrides:
            if override.role_id in user_role_set:
                if permission == "read" and override.can_read:
                    return True
                if permission == "write" and override.can_write:
                    return True
        return False
