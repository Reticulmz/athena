"""osu! stable account registration の integration contract を検証する test.

InMemory repository を使い, `/web/users` の validation, account creation, form error response を
end-to-end で確認する.
"""

from __future__ import annotations

import json
import os
import typing
from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from tests.support.app import create_in_memory_app as create_app
from tests.support.persistence import seed_role_sync

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

# ── Seed data ────────────────────────────────────────────────────────────

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED,
    position=0,
)


@contextmanager
def _test_env() -> Generator[None]:
    """Registration test 用の environment variable を一時設定する.

    Yields:
        None: `ENVIRONMENT` を test に設定した block を実行し, 終了時に元の値へ戻す.

    Notes:
        `DATABASE_URL` と `VALKEY_URL` は未設定の場合だけ local default を補う.
    """
    old = os.environ.get("ENVIRONMENT")
    os.environ["ENVIRONMENT"] = "test"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old


def _seed_default_role(app: Starlette) -> None:
    """Default role を command-side の in-memory persistence へ保存する.

    Args:
        app (Starlette): lifespan 済みの test application.

    Returns:
        None: registration に必要な role を保存して完了し, 呼び出し側へ値を返さない.

    Notes:
        `TestClient` の context に入った後にだけ呼び出す.
    """
    seed_role_sync(app, _DEFAULT_ROLE)


def _registration_form(
    *,
    username: str = "TestPlayer",
    email: str = "test@example.com",
    password: str = "ExamplePass1234",
    check: str = "0",
) -> dict[str, str]:
    """Stable registration endpoint 用の form data を組み立てる.

    Args:
        username (str): `user[username]` に設定する account name.
        email (str): `user[user_email]` に設定する email address.
        password (str): `user[password]` に設定する plaintext password.
        check (str): validation のみなら `1`, account 作成なら `0` を示す値.

    Returns:
        dict[str, str]: `/web/users` へ送信する form field の対応表.
    """
    return {
        "user[username]": username,
        "user[user_email]": email,
        "user[password]": password,
        "check": check,
    }


class TestRegistrationValidation:
    """`check=1` による registration validation-only 契約を検証する."""

    def test_check_only_returns_ok(self) -> None:
        """有効な `check=1` form が HTTP 200 と `ok` を返す契約を検証する.

        role を保存しない validation-only request を送る.
        account 作成を要求しない success response を確認する.

        Returns:
            None: validation response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/web/users",
                    data=_registration_form(check="1"),
                )

                assert response.status_code == HTTPStatus.OK
                assert response.content == b"ok"

    def test_check_only_does_not_create_user(self) -> None:
        """`check=1` が user を永続化しない契約を検証する.

        validation-only request の後に同じ username で `check=0` request を送る.
        account 作成が成功することを確認する.

        Returns:
            None: validation-only request の非永続性を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                # First: validate only
                resp_check = client.post(
                    "/web/users",
                    data=_registration_form(check="1"),
                )
                assert resp_check.status_code == HTTPStatus.OK

                # Second: actually create — should succeed because check=1 didn't create
                resp_create = client.post(
                    "/web/users",
                    data=_registration_form(check="0"),
                )
                assert resp_create.status_code == HTTPStatus.OK
                assert resp_create.content == b"ok"


class TestRegistrationCreation:
    """`check=0` による registration account creation 契約を検証する."""

    def test_successful_registration_returns_ok(self) -> None:
        """有効な `check=0` form が HTTP 200 と `ok` を返す契約を検証する.

        Default role を保存した application へ作成 request を送る.
        registration の成功 response を確認する.

        Returns:
            None: account creation response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                response = client.post(
                    "/web/users",
                    data=_registration_form(),
                )

                assert response.status_code == HTTPStatus.OK
                assert response.content == b"ok"


class TestRegistrationErrors:
    """不正な registration input に対する `form_error` response 契約を検証する."""

    def test_duplicate_username_returns_form_error(self) -> None:
        """重複 username の registration が username `form_error` を返す契約を検証する.

        最初に account を作成してから同じ username で再送し, HTTP 400 の error field を確認する.

        Returns:
            None: duplicate username response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                # First registration succeeds
                resp1 = client.post(
                    "/web/users",
                    data=_registration_form(),
                )
                assert resp1.status_code == HTTPStatus.OK

                # Second registration with same username fails
                resp2 = client.post(
                    "/web/users",
                    data=_registration_form(email="other@example.com"),
                )
                assert resp2.status_code == HTTPStatus.BAD_REQUEST

                body: dict[str, typing.Any] = json.loads(resp2.content)  # pyright: ignore[reportAny]  # json.loads returns Any
                assert "form_error" in body
                assert "username" in body["form_error"]["user"]

    def test_short_password_returns_form_error(self) -> None:
        """最小長未満の password が password `form_error` を返す契約を検証する.

        短い password を持つ form を送信し, HTTP 400 の password error field を確認する.

        Returns:
            None: short password response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/web/users",
                    data=_registration_form(password="ab"),
                )

                assert response.status_code == HTTPStatus.BAD_REQUEST

                body: dict[str, typing.Any] = json.loads(response.content)  # pyright: ignore[reportAny]  # json.loads returns Any
                assert "form_error" in body
                assert "password" in body["form_error"]["user"]

    def test_invalid_email_returns_form_error(self) -> None:
        """不正な email format が email `form_error` を返す契約を検証する.

        email address ではない文字列を送信し, HTTP 400 の email error field を確認する.

        Returns:
            None: invalid email response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/web/users",
                    data=_registration_form(email="not-an-email"),
                )

                assert response.status_code == HTTPStatus.BAD_REQUEST

                body: dict[str, typing.Any] = json.loads(response.content)  # pyright: ignore[reportAny]  # json.loads returns Any
                assert "form_error" in body
                assert "email" in body["form_error"]["user"]

    def test_duplicate_email_returns_form_error(self) -> None:
        """重複 email の registration が email `form_error` を返す契約を検証する.

        最初に account を作成してから同じ email を別 username で再送する.
        HTTP 400 の error field を確認する.

        Returns:
            None: duplicate email response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                resp1 = client.post(
                    "/web/users",
                    data=_registration_form(),
                )
                assert resp1.status_code == HTTPStatus.OK

                resp2 = client.post(
                    "/web/users",
                    data=_registration_form(username="OtherPlayer"),
                )
                assert resp2.status_code == HTTPStatus.BAD_REQUEST

                body: dict[str, typing.Any] = json.loads(resp2.content)  # pyright: ignore[reportAny]  # json.loads returns Any
                assert "form_error" in body
                assert "email" in body["form_error"]["user"]
