from __future__ import annotations

from typing import TYPE_CHECKING, final

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
