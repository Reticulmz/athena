"""PrivateMessageService の対象解決と配信可否を検証するユニットテスト.

in-memory user repository と session store を使用する.
packet 構築と実配信は transport 層の責務のため検証しない.
オンライン, offline, missing target と username normalization の結果を検証する.
"""

from __future__ import annotations

from datetime import UTC, datetime

from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.queries.chat.private_message_service import (
    PMDeliveryResult,
    PrivateMessageService,
)

# ── Constants ────────────────────────────────────────────────────────

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _make_user(*, user_id: int, username: str) -> User:
    """テスト用 user を正規化済み username とともに生成する.

    Args:
        user_id (int): user に設定する識別子. repository による採番前は 0 を渡す.
        username (str): 表示名と safe username の基になる入力値.

    Returns:
        User: login 情報を持つ未永続化 user.
    """
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
    """指定 user を online と扱うテスト用 session data を生成する.

    Args:
        user_id (int): session の対象 user ID.
        username (str): session に保存する表示 username.

    Returns:
        SessionData: private message を許可する既定 session data.
    """
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


class UserCommandHarness:
    """query service のために user 作成だけを公開する command harness.

    Attributes:
        _uow_factory (InMemoryUnitOfWorkFactory): user 作成を commit する in-memory factory.
    """

    _uow_factory: InMemoryUnitOfWorkFactory

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """User command の transaction factory を設定する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): user を永続化する factory.
        """
        self._uow_factory = uow_factory

    async def create(self, user: User) -> User:
        """User を作成して transaction を commit する.

        Args:
            user (User): 作成する未永続化 user.

        Returns:
            User: repository が採番した作成済み user.
        """
        async with self._uow_factory() as uow:
            created = await uow.users.create(user)
            await uow.commit()
            return created


_ServiceDeps = tuple[PrivateMessageService, UserCommandHarness, InMemorySessionStore]


def _make_service() -> _ServiceDeps:
    """PrivateMessageService と対象 user/session の in-memory 依存を構築する.

    Returns:
        _ServiceDeps: service, user command harness, session store の組.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    user_repo = InMemoryUserQueryRepository(uow_factory)
    user_commands = UserCommandHarness(uow_factory)
    session_store = InMemorySessionStore()
    svc = PrivateMessageService(
        user_repo=user_repo,
        session_store=session_store,
    )
    return svc, user_commands, session_store


# ===========================================================================
# resolve_target
# ===========================================================================


class TestResolveTargetOnline:
    """online target が存在し online 状態として解決されることを検証する."""

    async def test_returns_true_with_user_id_and_online(self) -> None:
        """Online session を持つ target の存在, ID, online 状態を検証する.

        Returns:
            None: resolve_target の3要素結果を検証して完了する.
        """
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
    """offline target が存在するが online ではないことを検証する."""

    async def test_returns_true_with_user_id_and_offline(self) -> None:
        """Session を持たない target の存在, ID, offline 状態を検証する.

        Returns:
            None: resolve_target の3要素結果を検証して完了する.
        """
        svc, user_repo, _session_store = _make_service()
        user = _make_user(user_id=0, username="OfflineUser")
        created = await user_repo.create(user)
        # No session created → offline

        exists, user_id, is_online = await svc.resolve_target("OfflineUser")

        assert exists is True
        assert user_id == created.id
        assert is_online is False


class TestResolveTargetNotFound:
    """存在しない target が ID なしで解決失敗することを検証する."""

    async def test_returns_false_with_none(self) -> None:
        """Missing target が存在しない結果と None ID を返すことを検証する.

        Returns:
            None: resolve_target の失敗結果を検証して完了する.
        """
        svc, _user_repo, _session_store = _make_service()

        exists, user_id, is_online = await svc.resolve_target("NoSuchUser")

        assert exists is False
        assert user_id is None
        assert is_online is False


class TestUsernameNormalization:
    """username normalization を使った target 解決を検証する."""

    async def test_resolves_with_spaces_in_name(self) -> None:
        """Space を含む username が保存済み target を解決することを検証する.

        Returns:
            None: normalization 後に online target が得られることを検証して完了する.
        """
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
        """Case が異なる username でも保存済み target を解決することを検証する.

        Returns:
            None: uppercase 入力で対象 user ID が得られることを検証して完了する.
        """
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
    """online target への配信可否を検証する."""

    async def test_returns_success_and_online(self) -> None:
        """Online target への配信が成功し target ID を返すことを検証する.

        Returns:
            None: deliver_message の success, target ID, online 状態を検証して完了する.
        """
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
    """offline target への配信可否を検証する."""

    async def test_returns_success_and_offline(self) -> None:
        """Offline target でも配信対象として成功することを検証する.

        Returns:
            None: deliver_message の success, target ID, offline 状態を検証して完了する.
        """
        svc, user_repo, _session_store = _make_service()
        target = _make_user(user_id=0, username="OfflineUser")
        target_created = await user_repo.create(target)
        # No session → offline

        result: PMDeliveryResult = await svc.deliver_message(target_name="OfflineUser")

        assert result.success is True
        assert result.target_id == target_created.id
        assert result.is_online is False


class TestDeliverMessageNotFound:
    """missing target への配信が失敗することを検証する."""

    async def test_returns_failure_for_nonexistent_user(self) -> None:
        """Missing target が success False と None target ID を返すことを検証する.

        Returns:
            None: deliver_message の失敗結果を検証して完了する.
        """
        svc, _user_repo, _session_store = _make_service()

        result: PMDeliveryResult = await svc.deliver_message(target_name="NoSuchUser")

        assert result.success is False
        assert result.target_id is None
        assert result.is_online is False
