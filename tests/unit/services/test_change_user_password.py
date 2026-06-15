"""Tests for the change user password command use-case."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from osu_server.domain.identity.system_users import create_bancho_bot_identity
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.identity import (
    ChangeUserPasswordCommandInput,
    ChangeUserPasswordCommandUseCase,
    ChangeUserPasswordStatus,
)
from tests.factories.domain import make_user


@final
@dataclass(slots=True)
class FakePasswordService:
    banned_passwords: set[str] = field(default_factory=set)
    prepared_passwords: list[str] = field(default_factory=list)
    checked_passwords: list[str] = field(default_factory=list)

    async def prepare_password(self, plain_password: str) -> str:
        self.prepared_passwords.append(plain_password)
        return f"hashed:{plain_password}"

    async def is_password_banned(self, password: str) -> bool:
        self.checked_passwords.append(password)
        return password in self.banned_passwords


def _make_use_case(
    *,
    password_service: FakePasswordService | None = None,
) -> tuple[
    ChangeUserPasswordCommandUseCase,
    InMemoryUnitOfWorkFactory,
    FakePasswordService,
]:
    uow_factory = InMemoryUnitOfWorkFactory()
    service = password_service or FakePasswordService()
    return (
        ChangeUserPasswordCommandUseCase(
            uow_factory=uow_factory,
            user_query_repository=InMemoryUserQueryRepository(uow_factory),
            password_service=service,
        ),
        uow_factory,
        service,
    )


async def _seed_user(
    uow_factory: InMemoryUnitOfWorkFactory,
    *,
    username: str = "TargetUser",
) -> None:
    async with uow_factory() as uow:
        _ = await uow.users.create(
            make_user(
                id=0,
                username=username,
                email=f"{username.lower()}@example.com",
                password_hash="old-hash",
            )
        )
        await uow.commit()


async def test_change_user_password_updates_existing_user_hash() -> None:
    use_case, uow_factory, password_service = _make_use_case()
    await _seed_user(uow_factory)

    result = await use_case.execute(
        ChangeUserPasswordCommandInput(
            username="TargetUser",
            plain_password="NewPass1234",
        )
    )

    assert result.status is ChangeUserPasswordStatus.CHANGED
    assert result.changed is True
    assert password_service.prepared_passwords == ["NewPass1234"]
    user = await InMemoryUserQueryRepository(uow_factory).get_by_safe_username("targetuser")
    assert user is not None
    assert user.password_hash == "hashed:NewPass1234"


async def test_change_user_password_returns_user_not_found_without_hashing() -> None:
    use_case, _, password_service = _make_use_case()

    result = await use_case.execute(
        ChangeUserPasswordCommandInput(
            username="MissingUser",
            plain_password="NewPass1234",
        )
    )

    assert result.status is ChangeUserPasswordStatus.USER_NOT_FOUND
    assert password_service.prepared_passwords == []


async def test_change_user_password_rejects_invalid_password_policy() -> None:
    use_case, uow_factory, password_service = _make_use_case()
    await _seed_user(uow_factory)

    result = await use_case.execute(
        ChangeUserPasswordCommandInput(
            username="TargetUser",
            plain_password="aaa",
        )
    )

    assert result.status is ChangeUserPasswordStatus.INVALID_PASSWORD
    assert result.errors == (
        "Password must be between 8 and 32 characters.",
        "Password must contain at least 4 unique characters.",
    )
    assert password_service.checked_passwords == []
    assert password_service.prepared_passwords == []


async def test_change_user_password_rejects_banned_password() -> None:
    password_service = FakePasswordService(banned_passwords={"NewPass1234"})
    use_case, uow_factory, _ = _make_use_case(password_service=password_service)
    await _seed_user(uow_factory)

    result = await use_case.execute(
        ChangeUserPasswordCommandInput(
            username="TargetUser",
            plain_password="NewPass1234",
        )
    )

    assert result.status is ChangeUserPasswordStatus.INVALID_PASSWORD
    assert len(result.errors) == 1
    assert "compromised" in result.errors[0]
    assert password_service.prepared_passwords == []


async def test_change_user_password_rejects_system_user() -> None:
    use_case, uow_factory, password_service = _make_use_case()
    await _seed_system_user(uow_factory)

    result = await use_case.execute(
        ChangeUserPasswordCommandInput(
            username="BanchoBot",
            plain_password="NewPass1234",
        )
    )

    assert result.status is ChangeUserPasswordStatus.SYSTEM_USER_DENIED
    assert password_service.prepared_passwords == []


async def _seed_system_user(uow_factory: InMemoryUnitOfWorkFactory) -> None:
    async with uow_factory() as uow:
        await uow.users.sync_system_user(create_bancho_bot_identity("BanchoBot"))
        await uow.commit()
