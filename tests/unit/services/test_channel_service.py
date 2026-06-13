"""ChannelService のユニットテスト。

InMemoryChannelRepository / InMemoryChannelStateStore を使用。
パケット構築・配信はトランスポート層の責務のため、本テストでは検証しない。

全分岐を検証:
- CRUD: create, get, get_all, update, delete
- join: 権限あり/権限なし/チャンネル不存在/冪等性/BYPASS_CHANNEL_ACL
- leave: 正常離脱
- get_delivery_targets: 正常配信先/未参加/書き込み権限なし/BYPASS_CHANNEL_ACL
- get_visible_channels / get_autojoin_channels: ACL フィルタリング + member_count
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.channel import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.identity.authorization import Privileges
from osu_server.infrastructure.state.memory.channel_state_store import (
    InMemoryChannelStateStore,
)
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.services.channel_service import ChannelService

# -- Constants ----------------------------------------------------------------

_NOW = datetime(2025, 1, 1, tzinfo=UTC)
_USER_ID = 100
_OTHER_USER_ID = 200
_DEFAULT_ROLE_ID = 1
_ADMIN_ROLE_ID = 2

# Privileges for a normal user (no special flags)
_NORMAL_PRIVS = int(Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED)
# Privileges with BYPASS_CHANNEL_ACL
_BYPASS_PRIVS = int(Privileges.NORMAL | Privileges.BYPASS_CHANNEL_ACL)
# Privileges with ADMIN (bypasses everything via has_privilege)
_ADMIN_PRIVS = int(Privileges.ADMIN)

_EXPECTED_TWO_CHANNELS = 2


# -- Helpers ------------------------------------------------------------------


def _make_channel(
    *,
    name: str = "#osu",
    topic: str = "General discussion",
    auto_join: bool = False,
    channel_id: int = 0,
) -> Channel:
    return Channel(
        id=channel_id,
        name=name,
        topic=topic,
        channel_type=ChannelType.PUBLIC,
        auto_join=auto_join,
        rate_limit_messages=None,
        rate_limit_window=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service() -> tuple[
    ChannelService,
    InMemoryChannelRepository,
    InMemoryChannelStateStore,
]:
    """テスト用の ChannelService + 全依存を構築する。"""
    repo = InMemoryChannelRepository()
    state = InMemoryChannelStateStore()

    svc = ChannelService(
        channel_repo=repo,
        channel_state=state,
    )
    return svc, repo, state


async def _seed_channel_with_acl(
    repo: InMemoryChannelRepository,
    *,
    name: str = "#osu",
    topic: str = "General discussion",
    auto_join: bool = False,
    overrides: list[tuple[int, bool, bool]] | None = None,
) -> Channel:
    """チャンネルを作成し、ロールオーバーライドを設定する。

    overrides: list of (role_id, can_read, can_write)
    """
    ch = await repo.create(_make_channel(name=name, topic=topic, auto_join=auto_join))
    if overrides:
        for role_id, can_read, can_write in overrides:
            repo.seed_override(
                ChannelRoleOverride(
                    channel_id=ch.id,
                    role_id=role_id,
                    can_read=can_read,
                    can_write=can_write,
                )
            )
    return ch


# -- CRUD Tests ---------------------------------------------------------------


class TestCreateChannel:
    async def test_create_returns_channel_with_generated_id(self) -> None:
        svc, _repo, _ = _make_service()
        ch = _make_channel()

        result = await svc.create_channel(ch)

        assert result.id > 0
        assert result.name == "#osu"

    async def test_create_duplicate_name_raises(self) -> None:
        svc, _repo, _ = _make_service()
        ch = _make_channel()
        _ = await svc.create_channel(ch)

        with pytest.raises(ValueError, match="already exists"):
            _ = await svc.create_channel(ch)


class TestGetChannel:
    async def test_get_existing_channel(self) -> None:
        svc, repo, _ = _make_service()
        _ = await repo.create(_make_channel())

        result = await svc.get_channel("#osu")

        assert result is not None
        assert result.name == "#osu"

    async def test_get_nonexistent_channel_returns_none(self) -> None:
        svc, _, _ = _make_service()

        result = await svc.get_channel("#nonexistent")

        assert result is None


class TestGetAllChannels:
    async def test_returns_all_public_channels(self) -> None:
        svc, repo, _ = _make_service()
        _ = await repo.create(_make_channel(name="#osu"))
        _ = await repo.create(_make_channel(name="#announce"))

        result = await svc.get_all_channels()

        assert len(result) == _EXPECTED_TWO_CHANNELS

    async def test_returns_empty_when_no_channels(self) -> None:
        svc, _, _ = _make_service()

        result = await svc.get_all_channels()

        assert result == []


class TestUpdateChannel:
    async def test_update_existing_channel(self) -> None:
        svc, repo, _ = _make_service()
        ch = await repo.create(_make_channel())
        updated = Channel(
            id=ch.id,
            name="#osu",
            topic="Updated topic",
            channel_type=ChannelType.PUBLIC,
            auto_join=True,
            rate_limit_messages=None,
            rate_limit_window=None,
            created_at=ch.created_at,
            updated_at=ch.updated_at,
        )

        result = await svc.update_channel(updated)

        assert result.topic == "Updated topic"
        assert result.auto_join is True

    async def test_update_nonexistent_channel_raises(self) -> None:
        svc, _, _ = _make_service()
        ch = _make_channel(channel_id=999)

        with pytest.raises(ValueError, match="not found"):
            _ = await svc.update_channel(ch)


class TestDeleteChannel:
    async def test_delete_existing_channel(self) -> None:
        svc, repo, _ = _make_service()
        ch = await repo.create(_make_channel())

        await svc.delete_channel(ch.id)

        assert await repo.get_by_name("#osu") is None

    async def test_delete_nonexistent_channel_is_noop(self) -> None:
        svc, _, _ = _make_service()

        # Should not raise
        await svc.delete_channel(999)


# -- Join Tests ---------------------------------------------------------------


class TestJoinChannel:
    async def test_join_with_read_permission_succeeds(self) -> None:
        """ロールの can_read=True で join 成功。"""
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, True)])

        result = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is True
        assert await state.is_member("#osu", _USER_ID)

    async def test_join_without_read_permission_fails(self) -> None:
        """ロールの can_read=False で join 失敗。"""
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, False, True)])

        result = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is False
        assert not await state.is_member("#osu", _USER_ID)

    async def test_join_nonexistent_channel_fails(self) -> None:
        """存在しないチャンネルへの join → False。"""
        svc, _, _state = _make_service()

        result = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#nonexistent",
        )

        assert result is False

    async def test_join_no_overrides_fails_closed(self) -> None:
        """オーバーライドなしのチャンネル → fail-closed で拒否。"""
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[])

        result = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is False
        assert not await state.is_member("#osu", _USER_ID)

    async def test_join_idempotent_already_member(self) -> None:
        """既に参加済みのチャンネルへの join は成功扱い (冪等)。"""
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, True)])

        # First join
        result1 = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        # Second join (idempotent)
        result2 = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result1 is True
        assert result2 is True
        assert await state.is_member("#osu", _USER_ID)

    async def test_join_bypass_channel_acl(self) -> None:
        """BYPASS_CHANNEL_ACL 権限でオーバーライドなしのチャンネルに参加可能。"""
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[])

        result = await svc.join(
            user_id=_USER_ID,
            user_privileges=_BYPASS_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is True
        assert await state.is_member("#osu", _USER_ID)

    async def test_join_admin_bypasses_acl(self) -> None:
        """ADMIN 権限は has_privilege 経由で全 ACL をバイパス。"""
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[])

        result = await svc.join(
            user_id=_USER_ID,
            user_privileges=_ADMIN_PRIVS,
            user_role_ids=[_ADMIN_ROLE_ID],
            channel_name="#osu",
        )

        assert result is True
        assert await state.is_member("#osu", _USER_ID)

    async def test_join_user_role_not_in_overrides_fails(self) -> None:
        """ユーザーのロールがオーバーライドに含まれない → 拒否。"""
        svc, repo, state = _make_service()
        # Override for role 99, but user has role 1
        _ = await _seed_channel_with_acl(repo, overrides=[(99, True, True)])

        result = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is False
        assert not await state.is_member("#osu", _USER_ID)


# -- Leave Tests --------------------------------------------------------------


class TestLeaveChannel:
    async def test_leave_removes_member(self) -> None:
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, True)])
        _ = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        await svc.leave(user_id=_USER_ID, channel_name="#osu")

        assert not await state.is_member("#osu", _USER_ID)

    async def test_leave_non_member_is_noop(self) -> None:
        """未参加ユーザーの leave は例外なし。"""
        svc, _, _state = _make_service()

        # Should not raise
        await svc.leave(user_id=_USER_ID, channel_name="#osu")


# -- get_delivery_targets Tests -----------------------------------------------


class TestGetDeliveryTargets:
    async def test_returns_members_excluding_sender(self) -> None:
        """送信者以外の全メンバー ID を返す。"""
        svc, repo, _state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, True)])

        # Both users join the channel
        _ = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )
        _ = await svc.join(
            user_id=_OTHER_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        result = await svc.get_delivery_targets(
            sender_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is not None
        assert result == {_OTHER_USER_ID}

    async def test_non_member_returns_none(self) -> None:
        """未参加ユーザーのメッセージ送信 → None。"""
        svc, repo, _state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, True)])

        result = await svc.get_delivery_targets(
            sender_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is None

    async def test_without_write_permission_returns_none(self) -> None:
        """can_write=False のロールでメッセージ送信 → None。"""
        svc, repo, _state = _make_service()
        # can_read=True (to join), can_write=False (cannot send)
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, False)])

        # Join the channel (read access is enough to join)
        _ = await svc.join(
            user_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        result = await svc.get_delivery_targets(
            sender_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is None

    async def test_bypass_channel_acl_bypasses_write_check(self) -> None:
        """BYPASS_CHANNEL_ACL 権限で書き込みACLをバイパス。"""
        svc, repo, _state = _make_service()
        # Channel with no write access for anyone
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, False)])

        # Join with bypass
        _ = await svc.join(
            user_id=_USER_ID,
            user_privileges=_BYPASS_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )
        # Add another user to receive the message
        _ = await svc.join(
            user_id=_OTHER_USER_ID,
            user_privileges=_BYPASS_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        result = await svc.get_delivery_targets(
            sender_id=_USER_ID,
            user_privileges=_BYPASS_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        assert result is not None
        assert result == {_OTHER_USER_ID}

    async def test_nonexistent_channel_returns_none(self) -> None:
        """存在しないチャンネルへの配信 → None (not a member)。"""
        svc, _, _ = _make_service()

        result = await svc.get_delivery_targets(
            sender_id=_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#nonexistent",
        )

        assert result is None

    async def test_admin_bypasses_write_acl(self) -> None:
        """ADMIN は has_privilege 経由で書き込み ACL もバイパス。"""
        svc, repo, _state = _make_service()
        _ = await _seed_channel_with_acl(repo, overrides=[(_DEFAULT_ROLE_ID, True, False)])

        # Admin joins and another user joins
        _ = await svc.join(
            user_id=_USER_ID,
            user_privileges=_ADMIN_PRIVS,
            user_role_ids=[_ADMIN_ROLE_ID],
            channel_name="#osu",
        )
        _ = await svc.join(
            user_id=_OTHER_USER_ID,
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
            channel_name="#osu",
        )

        result = await svc.get_delivery_targets(
            sender_id=_USER_ID,
            user_privileges=_ADMIN_PRIVS,
            user_role_ids=[_ADMIN_ROLE_ID],
            channel_name="#osu",
        )

        assert result is not None
        assert result == {_OTHER_USER_ID}


# -- get_visible_channels Tests -----------------------------------------------


class TestGetVisibleChannels:
    async def test_bypass_returns_all_channels_with_count(self) -> None:
        """BYPASS_CHANNEL_ACL → 全チャンネル + member_count 返却。"""
        svc, repo, state = _make_service()
        _ = await _seed_channel_with_acl(repo, name="#osu", overrides=[])
        _ = await _seed_channel_with_acl(repo, name="#announce", overrides=[])
        await state.add_member("#osu", _USER_ID)

        result = await svc.get_visible_channels(
            user_privileges=_BYPASS_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
        )

        assert len(result) == _EXPECTED_TWO_CHANNELS
        # Result is list of (Channel, member_count)
        names = {ch.name for ch, _ in result}
        assert names == {"#osu", "#announce"}
        # Check member count for #osu
        for ch, count in result:
            if ch.name == "#osu":
                assert count == 1
            else:
                assert count == 0

    async def test_normal_user_sees_only_readable_channels(self) -> None:
        """通常ユーザー → can_read=True のチャンネルのみ。"""
        svc, repo, _state = _make_service()
        _ = await _seed_channel_with_acl(
            repo, name="#osu", overrides=[(_DEFAULT_ROLE_ID, True, True)]
        )
        _ = await _seed_channel_with_acl(
            repo, name="#staff", overrides=[(_ADMIN_ROLE_ID, True, True)]
        )

        result = await svc.get_visible_channels(
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
        )

        assert len(result) == 1
        assert result[0][0].name == "#osu"

    async def test_no_overrides_means_invisible(self) -> None:
        """オーバーライドなし → 不可視。"""
        svc, repo, _ = _make_service()
        _ = await _seed_channel_with_acl(repo, name="#secret", overrides=[])

        result = await svc.get_visible_channels(
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
        )

        assert len(result) == 0

    async def test_admin_sees_all_channels(self) -> None:
        """ADMIN → 全チャンネル返却 (has_privilege 経由)。"""
        svc, repo, _ = _make_service()
        _ = await _seed_channel_with_acl(repo, name="#osu", overrides=[])
        _ = await _seed_channel_with_acl(repo, name="#staff", overrides=[])

        result = await svc.get_visible_channels(
            user_privileges=_ADMIN_PRIVS,
            user_role_ids=[_ADMIN_ROLE_ID],
        )

        assert len(result) == _EXPECTED_TWO_CHANNELS


# -- get_autojoin_channels Tests ----------------------------------------------


class TestGetAutojoinChannels:
    async def test_bypass_returns_all_autojoin_with_count(self) -> None:
        svc, repo, _ = _make_service()
        _ = await _seed_channel_with_acl(repo, name="#osu", auto_join=True, overrides=[])
        _ = await _seed_channel_with_acl(repo, name="#help", auto_join=False, overrides=[])

        result = await svc.get_autojoin_channels(
            user_privileges=_BYPASS_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
        )

        assert len(result) == 1
        assert result[0][0].name == "#osu"

    async def test_normal_user_gets_only_readable_autojoin(self) -> None:
        svc, repo, _ = _make_service()
        _ = await _seed_channel_with_acl(
            repo,
            name="#osu",
            auto_join=True,
            overrides=[(_DEFAULT_ROLE_ID, True, True)],
        )
        _ = await _seed_channel_with_acl(
            repo,
            name="#staff",
            auto_join=True,
            overrides=[(_ADMIN_ROLE_ID, True, True)],
        )

        result = await svc.get_autojoin_channels(
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
        )

        assert len(result) == 1
        assert result[0][0].name == "#osu"

    async def test_non_autojoin_excluded_even_if_readable(self) -> None:
        """auto_join=False のチャンネルは can_read=True でも返されない。"""
        svc, repo, _ = _make_service()
        _ = await _seed_channel_with_acl(
            repo,
            name="#osu",
            auto_join=False,
            overrides=[(_DEFAULT_ROLE_ID, True, True)],
        )

        result = await svc.get_autojoin_channels(
            user_privileges=_NORMAL_PRIVS,
            user_role_ids=[_DEFAULT_ROLE_ID],
        )

        assert len(result) == 0
