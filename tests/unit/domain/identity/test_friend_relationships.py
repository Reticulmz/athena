"""Identity contextのfriend relationshipとsystem user policyを検証する."""

from __future__ import annotations

import pytest

from osu_server.domain.identity.friends import (
    FriendableSystemUserCatalog,
    FriendRelationship,
)
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY, SystemUserIdentity


def test_friend_relationship_is_one_way_edge() -> None:
    """異なるownerとtargetの順序を持つfriend relationshipを別の一方向edgeとして扱うことを検証する.

    Returns:
        None: 逆向きrelationshipとの非同値性とset内での共存を検証して完了する.

    Raises:
        AssertionError: relationshipが方向を失いownerとtargetを交換しても同一になった場合.
    """
    relationship = FriendRelationship(owner_user_id=10, target_user_id=20)
    reverse = FriendRelationship(owner_user_id=20, target_user_id=10)

    assert relationship != reverse
    assert {relationship, reverse} == {
        FriendRelationship(owner_user_id=10, target_user_id=20),
        FriendRelationship(owner_user_id=20, target_user_id=10),
    }


def test_friend_relationship_rejects_self_target() -> None:
    """ownerと同じuserをtargetにするfriend relationshipを拒否することを検証する.

    Returns:
        None: self-target生成がValueErrorになることを検証して完了する.

    Raises:
        AssertionError: self-targetが有効なrelationshipとして生成された場合.
    """
    with pytest.raises(ValueError, match="self"):
        _ = FriendRelationship(owner_user_id=10, target_user_id=10)


def test_friendable_system_user_catalog_allows_banchobot_explicitly() -> None:
    """Default catalogがBanchoBotをsystem userかつfriendable targetとして許可することを検証する.

    Returns:
        None: BanchoBot IDへの両方のpolicy判定を検証して完了する.

    Raises:
        AssertionError: default catalogがBanchoBotを予約またはfriendableとして扱わない場合.
    """
    catalog = FriendableSystemUserCatalog.with_bancho_bot(BANCHO_BOT_IDENTITY)

    assert catalog.is_system_user(BANCHO_BOT_IDENTITY.user_id)
    assert catalog.is_friendable_system_user(BANCHO_BOT_IDENTITY.user_id)


def test_friendable_system_user_catalog_rejects_nonfriendable_system_user() -> None:
    """friendable集合にないsystem userをfriend targetとして許可しないことを検証する.

    Returns:
        None: system user識別とfriendable否定の両方を検証して完了する.

    Raises:
        AssertionError: 明示的な許可なしにsystem userをfriendableとして扱った場合.
    """
    catalog = FriendableSystemUserCatalog(
        system_users=(SystemUserIdentity(user_id=99, username="System"),),
        friendable_user_ids=frozenset(),
    )

    assert catalog.is_system_user(99)
    assert not catalog.is_friendable_system_user(99)
