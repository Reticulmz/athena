"""PrivateMessageService のユニットテスト。

InMemory 実装 (UserRepository, SessionStore) を使用。
パケット構築・配信はトランスポート層の責務のため、本テストでは検証しない。

検証パターン:
- オンラインユーザー宛: (True, user_id, True)
- オフラインユーザー宛: (True, user_id, False)
- 存在しないユーザー宛: (False, None, False)
- ユーザー名の正規化 (スペース → アンダースコア, 小文字化)
"""

from __future__ import annotations

from datetime import UTC, datetime

from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.queries.chat.private_message_service import (
    PMDeliveryResult,
    PrivateMessageService,
)

# ── Constants ────────────────────────────────────────────────────────

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _make_user(*, user_id: int, username: str) -> User:
    safe = User.normalize_username(username)
    return User(
        id=user_id,
        username=username,
        safe_username=safe,
        email=f"{safe}@test.local",
        password_hash="!test",
        country="XX",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_session(*, user_id: int, username: str) -> SessionData:
    return SessionData(
        user_id=user_id,
        username=username,
        privileges=1,
        country="XX",
        osu_version="20250101",
        utc_offset=0,
        display_city=False,
        client_hashes="",
        pm_private=False,
    )


_ServiceDeps = tuple[
    PrivateMessageService,
    InMemoryUserRepository,
    InMemorySessionStore,
]


def _make_service() -> _ServiceDeps:
    user_repo = InMemoryUserRepository()
    session_store = InMemorySessionStore()
    svc = PrivateMessageService(
        user_repo=user_repo,
        session_store=session_store,
    )
    return svc, user_repo, session_store


# ===========================================================================
# resolve_target
# ===========================================================================


class TestResolveTargetOnline:
    """オンラインユーザー宛: (True, user_id, True)"""

    async def test_returns_true_with_user_id_and_online(self) -> None:
        svc, user_repo, session_store = _make_service()
        user = _make_user(user_id=0, username="TargetUser")
        created = await user_repo.create(user)
        await session_store.create(
            created.id, "token-online", _make_session(user_id=created.id, username="TargetUser")
        )

        exists, user_id, is_online = await svc.resolve_target("TargetUser")

        assert exists is True
        assert user_id == created.id
        assert is_online is True


class TestResolveTargetOffline:
    """オフラインユーザー宛: (True, user_id, False)"""

    async def test_returns_true_with_user_id_and_offline(self) -> None:
        svc, user_repo, _session_store = _make_service()
        user = _make_user(user_id=0, username="OfflineUser")
        created = await user_repo.create(user)
        # No session created → offline

        exists, user_id, is_online = await svc.resolve_target("OfflineUser")

        assert exists is True
        assert user_id == created.id
        assert is_online is False


class TestResolveTargetNotFound:
    """存在しないユーザー宛: (False, None, False)"""

    async def test_returns_false_with_none(self) -> None:
        svc, _user_repo, _session_store = _make_service()

        exists, user_id, is_online = await svc.resolve_target("NoSuchUser")

        assert exists is False
        assert user_id is None
        assert is_online is False


class TestUsernameNormalization:
    """ユーザー名の正規化: スペース → アンダースコア、小文字化"""

    async def test_resolves_with_spaces_in_name(self) -> None:
        svc, user_repo, session_store = _make_service()
        user = _make_user(user_id=0, username="Target User")
        created = await user_repo.create(user)
        await session_store.create(
            created.id, "token-t", _make_session(user_id=created.id, username="Target User")
        )

        exists, user_id, is_online = await svc.resolve_target("Target User")

        assert exists is True
        assert user_id == created.id
        assert is_online is True

    async def test_resolves_case_insensitive(self) -> None:
        svc, user_repo, _session_store = _make_service()
        user = _make_user(user_id=0, username="MixedCase")
        created = await user_repo.create(user)

        exists, user_id, _is_online = await svc.resolve_target("MIXEDCASE")

        assert exists is True
        assert user_id == created.id


# ===========================================================================
# deliver_message
# ===========================================================================


class TestDeliverMessageOnline:
    """オンラインユーザー宛: success=True, is_online=True を返す"""

    async def test_returns_success_and_online(self) -> None:
        svc, user_repo, session_store = _make_service()
        target = _make_user(user_id=0, username="TargetUser")
        target_created = await user_repo.create(target)
        await session_store.create(
            target_created.id,
            "token-online",
            _make_session(user_id=target_created.id, username="TargetUser"),
        )

        result: PMDeliveryResult = await svc.deliver_message(target_name="TargetUser")

        assert result.success is True
        assert result.target_id == target_created.id
        assert result.is_online is True


class TestDeliverMessageOffline:
    """オフラインユーザー宛: success=True, is_online=False を返す"""

    async def test_returns_success_and_offline(self) -> None:
        svc, user_repo, _session_store = _make_service()
        target = _make_user(user_id=0, username="OfflineUser")
        target_created = await user_repo.create(target)
        # No session → offline

        result: PMDeliveryResult = await svc.deliver_message(target_name="OfflineUser")

        assert result.success is True
        assert result.target_id == target_created.id
        assert result.is_online is False


class TestDeliverMessageNotFound:
    """存在しないユーザー宛: success=False を返す"""

    async def test_returns_failure_for_nonexistent_user(self) -> None:
        svc, _user_repo, _session_store = _make_service()

        result: PMDeliveryResult = await svc.deliver_message(target_name="NoSuchUser")

        assert result.success is False
        assert result.target_id is None
        assert result.is_online is False
