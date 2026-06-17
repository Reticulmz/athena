from __future__ import annotations

import pytest

from osu_server.domain.identity.friends import (
    FriendableSystemUserCatalog,
    FriendRelationship,
)
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY, SystemUserIdentity


def test_friend_relationship_is_one_way_edge() -> None:
    relationship = FriendRelationship(owner_user_id=10, target_user_id=20)
    reverse = FriendRelationship(owner_user_id=20, target_user_id=10)

    assert relationship != reverse
    assert {relationship, reverse} == {
        FriendRelationship(owner_user_id=10, target_user_id=20),
        FriendRelationship(owner_user_id=20, target_user_id=10),
    }


def test_friend_relationship_rejects_self_target() -> None:
    with pytest.raises(ValueError, match="self"):
        _ = FriendRelationship(owner_user_id=10, target_user_id=10)


def test_friendable_system_user_catalog_allows_banchobot_explicitly() -> None:
    catalog = FriendableSystemUserCatalog.with_bancho_bot(BANCHO_BOT_IDENTITY)

    assert catalog.is_system_user(BANCHO_BOT_IDENTITY.user_id)
    assert catalog.is_friendable_system_user(BANCHO_BOT_IDENTITY.user_id)


def test_friendable_system_user_catalog_rejects_nonfriendable_system_user() -> None:
    catalog = FriendableSystemUserCatalog(
        system_users=(SystemUserIdentity(user_id=99, username="System"),),
        friendable_user_ids=frozenset(),
    )

    assert catalog.is_system_user(99)
    assert not catalog.is_friendable_system_user(99)
