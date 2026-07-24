"""SessionStoreのmemory実装に対するsession lifecycle契約を検証する."""

from __future__ import annotations

from dataclasses import replace

import pytest

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionAuthorization, SessionData
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore

_SESSION = SessionData(
    user_id=1,
    username="peppy",
    privileges=1,
    country="JP",
    osu_version="20231111",
    utc_offset=9,
    display_city=True,
    client_hashes="hash1:hash2",
    pm_private=False,
)


@pytest.fixture
def store() -> InMemorySessionStore:
    """各testへtokenとuserの対応が空のsession storeを提供する.

    Returns:
        InMemorySessionStore: 各testで独立して使用するsession store.
    """
    return InMemorySessionStore()


async def test_create_and_get(store: InMemorySessionStore) -> None:
    """sessionを作成したときtoken検索が同じusernameとprivilegeを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    result = await store.get("abc-123")

    assert result is not None
    assert result.username == "peppy"
    assert result.privileges == 1


async def test_get_nonexistent_returns_none(store: InMemorySessionStore) -> None:
    """未知tokenを検索したときNoneを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    result = await store.get("nonexistent-token")

    assert result is None


async def test_get_by_user(store: InMemorySessionStore) -> None:
    """sessionを作成したときuser ID検索が同じsession dataを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    result = await store.get_by_user(user_id=1)

    assert result is not None
    assert result.username == "peppy"


async def test_get_by_user_nonexistent_returns_none(store: InMemorySessionStore) -> None:
    """未知user IDを検索したときNoneを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    result = await store.get_by_user(user_id=9999)

    assert result is None


async def test_delete(store: InMemorySessionStore) -> None:
    """tokenでsessionを削除したときtokenとuserの両検索がNoneを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    await store.delete("abc-123")

    assert await store.get("abc-123") is None
    assert await store.get_by_user(user_id=1) is None


async def test_exists_true(store: InMemorySessionStore) -> None:
    """sessionを作成したtokenに対してexistsがTrueを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    assert await store.exists("abc-123") is True


async def test_exists_false(store: InMemorySessionStore) -> None:
    """未知tokenに対してexistsがFalseを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    assert await store.exists("nonexistent-token") is False


async def test_create_overwrites_previous_session(store: InMemorySessionStore) -> None:
    """同じuserへ新tokenを作成したとき旧tokenを失効し新sessionへ置換することを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    data_old = replace(_SESSION, country="US")
    data_new = replace(_SESSION, country="JP")

    await store.create(user_id=1, token="old-token", data=data_old)
    await store.create(user_id=1, token="new-token", data=data_new)

    # Old token should be gone
    assert await store.get("old-token") is None
    assert await store.exists("old-token") is False

    # New token should be active
    result = await store.get("new-token")
    assert result is not None
    assert result.country == "JP"

    # get_by_user returns the new session
    result_by_user = await store.get_by_user(user_id=1)
    assert result_by_user is not None
    assert result_by_user.country == "JP"


async def test_refresh_existing_token(store: InMemorySessionStore) -> None:
    """既存tokenをrefreshしたときsessionを保ったままTrueを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    result = await store.refresh("abc-123")

    assert result is True


async def test_refresh_nonexistent_token(store: InMemorySessionStore) -> None:
    """未知tokenをrefreshしたときFalseを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    result = await store.refresh("nonexistent-token")

    assert result is False


# ---------------------------------------------------------------------------
# delete_by_user
# ---------------------------------------------------------------------------


async def test_delete_by_user_removes_session(store: InMemorySessionStore) -> None:
    """User IDでsessionを削除したとき両lookupとexistsから消えることを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    await store.delete_by_user(user_id=1)

    assert await store.get("abc-123") is None
    assert await store.get_by_user(user_id=1) is None
    assert await store.exists("abc-123") is False


async def test_delete_by_user_idempotent(store: InMemorySessionStore) -> None:
    """未知user IDを削除したとき例外を送出せずno-opで完了することを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    # Should not raise
    await store.delete_by_user(user_id=9999)


async def test_delete_by_user_does_not_affect_other_users(store: InMemorySessionStore) -> None:
    """一方のuserを削除したとき別userのsessionを保持することを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    other_session = replace(_SESSION, user_id=2, username="cookiezi")
    await store.create(user_id=1, token="token-1", data=_SESSION)
    await store.create(user_id=2, token="token-2", data=other_session)

    await store.delete_by_user(user_id=1)

    assert await store.get("token-1") is None
    result = await store.get("token-2")
    assert result is not None
    assert result.username == "cookiezi"


# ---------------------------------------------------------------------------
# list_active_sessions
# ---------------------------------------------------------------------------


async def test_list_active_sessions_empty_store(store: InMemorySessionStore) -> None:
    """空storeのactive session一覧を取得したとき空listを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    result = await store.list_active_sessions()

    assert result == []


async def test_list_active_sessions_returns_all(store: InMemorySessionStore) -> None:
    """3sessionを作成したときactive一覧が全user IDを含むことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    session_2 = replace(_SESSION, user_id=2, username="cookiezi")
    session_3 = replace(_SESSION, user_id=3, username="whitecat")

    await store.create(user_id=1, token="t1", data=_SESSION)
    await store.create(user_id=2, token="t2", data=session_2)
    await store.create(user_id=3, token="t3", data=session_3)

    result = await store.list_active_sessions()

    assert sorted(session.user_id for session in result) == [1, 2, 3]


async def test_list_active_sessions_excludes_deleted(store: InMemorySessionStore) -> None:
    """sessionを削除したuserがactive一覧から除かれることを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    session_2 = replace(_SESSION, user_id=2, username="cookiezi")
    await store.create(user_id=1, token="t1", data=_SESSION)
    await store.create(user_id=2, token="t2", data=session_2)

    await store.delete_by_user(user_id=1)

    result = await store.list_active_sessions()

    assert [session.user_id for session in result] == [2]


# ---------------------------------------------------------------------------
# update_authorization (Feature Flag Protocol — RED phase with flag OFF)
# ---------------------------------------------------------------------------


async def test_update_authorization_updates_privileges_and_role_ids(
    store: InMemorySessionStore,
) -> None:
    """Active sessionのauthorization更新でprivilegesとrole IDsが置換されることを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.NORMAL | Privileges.MODERATOR,
        role_ids=(1, 2),
    )
    result = await store.update_authorization(user_id=1, authorization=new_auth)

    assert result is True
    session = await store.get("abc-123")
    assert session is not None
    assert session.privileges == int(Privileges.NORMAL | Privileges.MODERATOR)
    assert session.role_ids == (1, 2)


async def test_update_authorization_preserves_other_fields(
    store: InMemorySessionStore,
) -> None:
    """authorizationを更新したとき他のsession fieldを変更しないことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.MODERATOR,
        role_ids=(3,),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session = await store.get("abc-123")
    assert session is not None
    assert session.user_id == 1
    assert session.username == "peppy"
    assert session.country == "JP"
    assert session.osu_version == "20231111"
    assert session.utc_offset == 9
    assert session.display_city is True
    assert session.client_hashes == "hash1:hash2"
    assert session.pm_private is False
    assert session.silence_end == 0


async def test_update_authorization_preserves_token_lookup(
    store: InMemorySessionStore,
) -> None:
    """authorization更新後にtoken lookupが更新済みsessionを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.NORMAL,
        role_ids=(),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session = await store.get("abc-123")
    assert session is not None
    assert session.privileges == int(Privileges.NORMAL)
    assert session.role_ids == ()


async def test_update_authorization_preserves_user_lookup(
    store: InMemorySessionStore,
) -> None:
    """authorization更新後にuser lookupが更新済みsessionを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.VERIFIED,
        role_ids=(5,),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session = await store.get_by_user(user_id=1)
    assert session is not None
    assert session.privileges == int(Privileges.VERIFIED)
    assert session.role_ids == (5,)


async def test_update_authorization_returns_false_for_offline_user(
    store: InMemorySessionStore,
) -> None:
    """Offline userのauthorization更新がstateを作らずFalseを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    new_auth = SessionAuthorization(
        privileges=Privileges.NORMAL,
        role_ids=(),
    )
    result = await store.update_authorization(user_id=9999, authorization=new_auth)

    assert result is False
    assert await store.get_by_user(user_id=9999) is None
    assert await store.list_active_sessions() == []


async def test_update_authorization_does_not_affect_other_users(
    store: InMemorySessionStore,
) -> None:
    """一方のuserのauthorization更新が別userのsessionを変えないことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    other_session = replace(_SESSION, user_id=2, username="cookiezi")
    await store.create(user_id=1, token="token-1", data=_SESSION)
    await store.create(user_id=2, token="token-2", data=other_session)

    new_auth = SessionAuthorization(
        privileges=Privileges.MODERATOR,
        role_ids=(1,),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session1 = await store.get("token-1")
    assert session1 is not None
    assert session1.privileges == int(Privileges.MODERATOR)

    session2 = await store.get("token-2")
    assert session2 is not None
    assert session2.privileges == 1  # original _SESSION value unchanged


async def test_update_authorization_idempotent(
    store: InMemorySessionStore,
) -> None:
    """同じauthorizationを繰返し更新しても成功結果とsession値が不変であることを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.SUPPORTER | Privileges.VERIFIED,
        role_ids=(1, 2),
    )
    result1 = await store.update_authorization(user_id=1, authorization=new_auth)
    result2 = await store.update_authorization(user_id=1, authorization=new_auth)

    assert result1 is True
    assert result2 is True
    session = await store.get("abc-123")
    assert session is not None
    assert session.privileges == int(Privileges.SUPPORTER | Privileges.VERIFIED)
    assert session.role_ids == (1, 2)


async def test_update_authorization_token_mapping_unchanged(
    store: InMemorySessionStore,
) -> None:
    """authorization更新がtokenとuser IDの双方向mappingを変えないことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.NONE,
        role_ids=(),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session_by_user = await store.get_by_user(user_id=1)
    assert session_by_user is not None
    assert session_by_user.user_id == 1

    session_by_token = await store.get("abc-123")
    assert session_by_token is not None
    assert session_by_token.user_id == 1


# ---------------------------------------------------------------------------
# update_pm_private
# ---------------------------------------------------------------------------


async def test_update_pm_private_updates_session(
    store: InMemorySessionStore,
) -> None:
    """Active sessionのprivate message設定を更新したときflagだけが指定値へ変わることを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    result = await store.update_pm_private(user_id=1, enabled=True)

    assert result is True
    session = await store.get("abc-123")
    assert session is not None
    assert session.pm_private is True

    result = await store.update_pm_private(user_id=1, enabled=False)

    assert result is True
    session = await store.get("abc-123")
    assert session is not None
    assert session.pm_private is False


async def test_update_pm_private_preserves_other_fields(
    store: InMemorySessionStore,
) -> None:
    """Private message設定を更新したとき他のsession fieldを保持することを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    original = replace(
        _SESSION,
        privileges=int(Privileges.MODERATOR),
        role_ids=(3,),
        silence_end=123,
    )
    await store.create(user_id=1, token="abc-123", data=original)

    _ = await store.update_pm_private(user_id=1, enabled=True)

    session = await store.get("abc-123")
    assert session is not None
    assert session.user_id == 1
    assert session.username == "peppy"
    assert session.privileges == int(Privileges.MODERATOR)
    assert session.role_ids == (3,)
    assert session.country == "JP"
    assert session.osu_version == "20231111"
    assert session.utc_offset == 9
    assert session.display_city is True
    assert session.client_hashes == "hash1:hash2"
    assert session.silence_end == 123


async def test_update_pm_private_returns_false_for_offline_user(
    store: InMemorySessionStore,
) -> None:
    """Offline userのprivate message設定更新がstateを作らずFalseを返すことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    result = await store.update_pm_private(user_id=9999, enabled=True)

    assert result is False
    assert await store.get_by_user(user_id=9999) is None
    assert await store.list_active_sessions() == []


async def test_update_pm_private_token_mapping_unchanged(
    store: InMemorySessionStore,
) -> None:
    """Private message設定更新がtokenとuser IDの双方向mappingを変えないことを確認する.

    Args:
        store (InMemorySessionStore): 検証対象の空のsession store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    _ = await store.update_pm_private(user_id=1, enabled=True)

    session_by_user = await store.get_by_user(user_id=1)
    assert session_by_user is not None
    assert session_by_user.pm_private is True

    session_by_token = await store.get("abc-123")
    assert session_by_token is not None
    assert session_by_token.pm_private is True


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


async def test_inmemory_session_store_is_instance_of_session_store() -> None:
    """memory実装を生成したときSessionStore Protocolとして認識されることを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    store = InMemorySessionStore()

    assert isinstance(store, SessionStore)
