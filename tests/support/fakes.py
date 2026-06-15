from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final, override

from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.storage.blobs import Blob, BlobStored
from osu_server.services.commands.scores import SubmitScoreUseCase
from osu_server.services.password_service import PasswordService
from osu_server.services.score_authorization_service import ScoreAuthorizationService

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import SessionAuthorization
    from osu_server.domain.scores.replay import Replay
    from osu_server.domain.scores.score import Score
    from osu_server.domain.scores.submission import ScoreSubmission
    from osu_server.domain.system_user import SystemUserIdentity
    from osu_server.infrastructure.security.hibp import HIBPClient
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class FakeHIBPClient:
    """HIBPClient の typed fake。

    本物のネットワーク通信を行わず、指定されたパスワードの漏洩状態をシミュレートする。
    """

    def __init__(self, compromised_passwords: set[str] | None = None) -> None:
        self.compromised_passwords: set[str] = compromised_passwords or set()
        self.calls: list[str] = []

    async def is_password_compromised(self, password: str) -> bool:
        """パスワードが漏洩しているかアサートする。"""
        self.calls.append(password)
        return password in self.compromised_passwords


# Ensure FakeHIBPClient implements the HIBPClient protocol
_: HIBPClient = FakeHIBPClient()


@final
class ErrorRaisingUserRepository:
    """UserQueryRepository that raises on get_by_safe_username when armed.

    Delegates all operations to an inner UserQueryRepository.
    Used to simulate DB failures in tests without AsyncMock monkey-patching.
    """

    def __init__(self, inner: UserQueryRepository, error: Exception) -> None:
        self._inner = inner
        self._error = error
        self._armed = False

    def arm(self) -> None:
        """Arm the repository to raise on get_by_safe_username calls."""
        self._armed = True

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._inner.get_by_id(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        if self._armed:
            raise self._error
        return await self._inner.get_by_safe_username(safe_username)

    async def get_by_email(self, email: str) -> User | None:
        return await self._inner.get_by_email(email)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        return await self._inner.is_username_disallowed(safe_username)


@final
class StaticScoreUserRepository:
    """Single-user repository for score authorization tests."""

    def __init__(self, user: User) -> None:
        self._user = user

    async def create(self, user: User) -> User:
        self._user = user
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return self._user if self._user.id == user_id else None

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        return self._user if self._user.safe_username == safe_username else None

    async def get_by_email(self, email: str) -> User | None:
        return self._user if self._user.email == email else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        _ = safe_username
        return False

    async def add_disallowed_username(self, safe_username: str) -> None:
        _ = safe_username

    async def update_country(self, user_id: int, country: str) -> None:
        if self._user.id == user_id:
            self._user.country = country

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        _ = identity


@final
class StaticPasswordService(PasswordService):
    """PasswordService test double with one accepted password-md5."""

    def __init__(self, accepted_password_md5: str) -> None:
        super().__init__(hibp_client=None, banned_passwords=[])
        self._accepted_password_md5 = accepted_password_md5

    @override
    async def verify(self, hashed: str, password: str) -> bool:
        _ = hashed
        return password == self._accepted_password_md5


@final
class StaticSessionStore:
    """SessionStore test double with an optional active session."""

    def __init__(self, session: SessionData | None) -> None:
        self._session = session
        self._token = f"token-{session.user_id}" if session is not None else ""

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        _ = user_id
        self._token = token
        self._session = data

    async def get(self, token: str) -> SessionData | None:
        return self._session if self._session is not None and token == self._token else None

    async def get_by_user(self, user_id: int) -> SessionData | None:
        return (
            self._session
            if self._session is not None and self._session.user_id == user_id
            else None
        )

    async def delete(self, token: str) -> None:
        if token == self._token:
            self._session = None

    async def exists(self, token: str) -> bool:
        return self._session is not None and token == self._token

    async def refresh(self, token: str) -> bool:
        return await self.exists(token)

    async def delete_by_user(self, user_id: int) -> None:
        if self._session is not None and self._session.user_id == user_id:
            self._session = None

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        if self._session is None or self._session.user_id != user_id:
            return False
        self._session.privileges = int(authorization.privileges)
        self._session.role_ids = authorization.role_ids
        return True

    async def get_all_user_ids(self) -> list[int]:
        return [] if self._session is None else [self._session.user_id]


def make_score_authorization_service(
    *,
    user_id: int = 1000,
    username: str = "test_user",
    password_md5: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    create_session: bool = True,
) -> ScoreAuthorizationService:
    """Create repository-backed score auth with explicit test doubles."""
    now = datetime.now(UTC)
    user = User(
        id=user_id,
        username=username,
        safe_username=User.normalize_username(username),
        email=f"{username}@example.com",
        password_hash="!static-test-hash",
        country="JP",
        created_at=now,
        updated_at=now,
    )
    session = (
        SessionData(
            user_id=user_id,
            username=username,
            privileges=1,
            country="JP",
            osu_version="20240101",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        )
        if create_session
        else None
    )
    return ScoreAuthorizationService(
        user_repo=StaticScoreUserRepository(user),
        password_service=StaticPasswordService(password_md5),
        session_store=StaticSessionStore(session),
    )


class UowScoreRepositoryView:
    """Compatibility view over score command state for tests."""

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, score: Score) -> Score:
        async with self._unit_of_work_factory() as uow:
            created = await uow.scores.create(score)
            await uow.commit()
            return created

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.exists_by_online_checksum(checksum)

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.get_by_online_checksum(checksum)

    async def get_by_id(self, score_id: int) -> Score | None:
        async with self._unit_of_work_factory() as uow:
            return await uow.scores.get_by_id(score_id)


class UowScoreSubmissionRepositoryView:
    """Compatibility view over score submission command state for tests."""

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        async with self._unit_of_work_factory() as uow:
            created = await uow.submissions.create(submission)
            await uow.commit()
            return created

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        async with self._unit_of_work_factory() as uow:
            return await uow.submissions.get_by_fingerprint(fingerprint)

    async def update_state(
        self,
        submission_id: int,
        state: str,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        async with self._unit_of_work_factory() as uow:
            await uow.submissions.update_state(submission_id, state, result_snapshot)
            await uow.commit()


class UowReplayRepositoryView:
    """Compatibility view over replay command state for tests."""

    def __init__(self, unit_of_work_factory: InMemoryUnitOfWorkFactory) -> None:
        self._unit_of_work_factory: InMemoryUnitOfWorkFactory = unit_of_work_factory

    async def create(self, replay: Replay) -> Replay:
        async with self._unit_of_work_factory() as uow:
            created = await uow.replays.create(replay)
            await uow.commit()
            return created

    async def exists_by_checksum(self, checksum: str) -> bool:
        async with self._unit_of_work_factory() as uow:
            return await uow.replays.exists_by_checksum(checksum)


type ScoreRepositoryViews = tuple[
    UowScoreRepositoryView,
    UowScoreSubmissionRepositoryView,
    UowReplayRepositoryView,
]


def make_score_repository_views(
    unit_of_work_factory: InMemoryUnitOfWorkFactory,
) -> ScoreRepositoryViews:
    return (
        UowScoreRepositoryView(unit_of_work_factory),
        UowScoreSubmissionRepositoryView(unit_of_work_factory),
        UowReplayRepositoryView(unit_of_work_factory),
    )


def make_submit_score_use_case(
    unit_of_work_factory: InMemoryUnitOfWorkFactory,
) -> SubmitScoreUseCase:
    return SubmitScoreUseCase(unit_of_work_factory=unit_of_work_factory)


class StubBlobStorageService:
    """Typed fake for tests that need blob write verification."""

    def __init__(self, *, fail_writes: bool = False) -> None:
        self.fail_writes: bool = fail_writes
        self.stored: list[Blob] = []
        self.writes: list[bytes] = []

    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
        if self.fail_writes:
            raise RuntimeError("blob write failed")

        digest = hashlib.sha256(data).hexdigest()
        blob = Blob(
            id=len(self.stored) + 1,
            sha256=digest,
            byte_size=len(data),
            content_type=content_type,
            storage_backend="test",
            storage_key=f"sha256/{digest[:2]}/{digest[2:4]}/{digest}",
            created_at=datetime.now(UTC),
        )
        self.stored.append(blob)
        self.writes.append(data)
        return BlobStored(blob=blob)


type ScorePayloadDecryptFactory = Callable[[bytes, bytes, str | None], DecryptedPayload]


class StubScorePayloadDecryptor:
    """Typed fake for score payload decryption in submission tests."""

    def __init__(
        self,
        result: DecryptedPayload | None = None,
        *,
        factory: ScorePayloadDecryptFactory | None = None,
    ) -> None:
        self._result: DecryptedPayload | None = result
        self._factory: ScorePayloadDecryptFactory | None = factory
        self.calls: list[tuple[bytes, bytes, str | None]] = []

    def set_result(self, result: DecryptedPayload) -> None:
        self._result = result
        self._factory = None

    def set_factory(self, factory: ScorePayloadDecryptFactory) -> None:
        self._factory = factory

    def decrypt_score_payload(
        self,
        encrypted: bytes,
        iv: bytes,
        osu_version: str | None,
    ) -> DecryptedPayload:
        self.calls.append((encrypted, iv, osu_version))
        if self._factory is not None:
            return self._factory(encrypted, iv, osu_version)
        if self._result is None:
            raise AssertionError("StubScorePayloadDecryptor result was not configured")
        return self._result
