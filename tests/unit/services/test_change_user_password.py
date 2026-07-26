"""ユーザーpassword変更command use-caseの契約を検証するtest module."""

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
    """password policy gatewayを模倣して呼出し履歴を保持するfake.

    Attributes:
        banned_passwords (set[str]): 拒否対象として扱う平文passwordの集合.
        prepared_passwords (list[str]): hash化を依頼された平文passwordの履歴.
        checked_passwords (list[str]): 禁止判定を依頼されたpasswordの履歴.
    """

    banned_passwords: set[str] = field(default_factory=set)
    prepared_passwords: list[str] = field(default_factory=list)
    checked_passwords: list[str] = field(default_factory=list)

    async def prepare_password(self, plain_password: str) -> str:
        """test用の決定的なpassword hashを作成する.

        Args:
            plain_password (str): hash化を依頼された平文password.

        Returns:
            str: 呼出し履歴へ記録した平文passwordに対応するtest用hash.
        """
        self.prepared_passwords.append(plain_password)
        return f"hashed:{plain_password}"

    async def is_password_banned(self, password: str) -> bool:
        """passwordが禁止集合に含まれるかを返す.

        Args:
            password (str): 禁止判定を行う平文password.

        Returns:
            bool: passwordが禁止集合に含まれる場合はTrue.
        """
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
    """password変更test用のuse caseと依存fakeを作成する.

    Args:
        password_service (FakePasswordService | None): 使用するpassword service.
            未指定時は新規fake.

    Returns:
        tuple[ChangeUserPasswordCommandUseCase, InMemoryUnitOfWorkFactory, FakePasswordService]:
            use caseと永続化状態を確認するfactoryおよびpassword service.
    """
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
    """password変更対象となる通常userをmemory repositoryへ登録する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): userを登録するmemory Unit of Work factory.
        username (str): 登録するuserの表示名.

    Returns:
        None: 登録とcommitを完了し呼出し側へ値を返さない.
    """
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
    """既存userのpassword hash更新契約を検証する.

    有効なtarget userの平文passwordを変更しpassword serviceの入力と永続化されたhashを確認する.

    Returns:
        None: 更新結果とobservableな依存service呼出しを検証して完了する.
    """
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
    """存在しないuserではpassword hash化を行わない契約を検証する.

    未登録usernameを指定してUSER_NOT_FOUNDとpassword service未呼出しを確認する.

    Returns:
        None: not-found結果とhash化履歴を検証して完了する.
    """
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
    """Password policy違反を変更前に拒否する契約を検証する.

    長さと一意文字数が不足する平文passwordを指定してvalidation errorと副作用なしを確認する.

    Returns:
        None: invalid-password結果と依存service未呼出しを検証して完了する.
    """
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
    """禁止済みpasswordをhash化せず拒否する契約を検証する.

    password serviceが禁止と判定する平文passwordを指定してvalidation errorとhash化未実行を確認する.

    Returns:
        None: 禁止passwordの拒否結果とhash化履歴を検証して完了する.
    """
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
    """System userのpassword変更を拒否する契約を検証する.

    BanchoBot identityを対象に指定してSYSTEM_USER_DENIEDとpassword service未呼出しを確認する.

    Returns:
        None: system userの拒否結果とhash化履歴を検証して完了する.
    """
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
    """BanchoBot system userをmemory repositoryへ同期する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): system userを同期するmemory Unit of Work factory.

    Returns:
        None: 同期とcommitを完了し呼出し側へ値を返さない.
    """
    async with uow_factory() as uow:
        await uow.users.sync_system_user(create_bancho_bot_identity("BanchoBot"))
        await uow.commit()
