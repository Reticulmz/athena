from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

from osu_server.domain.blob import Blob, BlobStored
from osu_server.domain.score.decryption import DecryptedPayload

if TYPE_CHECKING:
    from osu_server.domain.system_user import SystemUserIdentity
    from osu_server.domain.user import User
    from osu_server.infrastructure.security.hibp import HIBPClient
    from osu_server.repositories.memory.user_repository import InMemoryUserRepository


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
    """UserRepository that raises on get_by_safe_username when armed.

    Delegates all operations to an inner InMemoryUserRepository.
    Used to simulate DB failures in tests without AsyncMock monkey-patching.
    """

    def __init__(self, inner: InMemoryUserRepository, error: Exception) -> None:
        self._inner = inner
        self._error = error
        self._armed = False

    def arm(self) -> None:
        """Arm the repository to raise on get_by_safe_username calls."""
        self._armed = True

    async def create(self, user: User) -> User:
        return await self._inner.create(user)

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

    async def add_disallowed_username(self, safe_username: str) -> None:
        await self._inner.add_disallowed_username(safe_username)

    async def update_country(self, user_id: int, country: str) -> None:
        await self._inner.update_country(user_id, country)

    async def sync_system_user(self, identity: SystemUserIdentity) -> None:
        await self._inner.sync_system_user(identity)


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
