"""osu! stable client の Bancho login と polling を検証する integration test.

InMemory repository を使い, account registration, login response, session polling の
end-to-end contract を確認する.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from starlette.testclient import TestClient

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from tests.factories.domain import make_channel, make_channel_role_override
from tests.support.app import create_in_memory_app as create_app
from tests.support.persistence import seed_channel, seed_channel_override, seed_role_sync

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

# ── Constants ────────────────────────────────────────────────────────────

_TEST_USERNAME = "TestPlayer"
_TEST_EMAIL = "test@example.com"
_TEST_PASSWORD = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD.encode()).hexdigest()
_TEST_CLIENT_INFO = "b20240101.1|9|1|abc:def:ghi:jkl:mno|0"

_LOGIN_REPLY_ID = int(ServerPacketID.LOGIN_REPLY)
_PROTOCOL_VERSION_ID = int(ServerPacketID.PROTOCOL_VERSION)
_LOGIN_PERMISSIONS_ID = int(ServerPacketID.LOGIN_PERMISSIONS)

_PACKET_HEADER_SIZE = 7  # 2 (id) + 1 (compression) + 4 (content_length)

_AUTH_FAILED_USER_ID = -1
_BANCHO_URL = "http://c.athena.localhost/"

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED,
    position=0,
)

_EXPECTED_MIN_PACKETS = 10


# ── Helpers ──────────────────────────────────────────────────────────────


@contextmanager
def _test_env() -> Generator[None]:
    """Test 実行に必要な environment variable を一時設定する.

    Yields:
        None: `ENVIRONMENT` と `DOMAIN` を設定した block を実行し, 終了時に元の値へ戻す.

    Notes:
        `DATABASE_URL` と `VALKEY_URL` は未設定の場合だけ local default を補う.
    """
    old_environment = os.environ.get("ENVIRONMENT")
    old_domain = os.environ.get("DOMAIN")
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old_environment is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old_environment
        if old_domain is None:
            _ = os.environ.pop("DOMAIN", None)
        else:
            os.environ["DOMAIN"] = old_domain


def _seed_default_role(app: Starlette) -> None:
    """Default role を command-side の in-memory persistence へ保存する.

    Args:
        app (Starlette): lifespan 済みの test application.

    Returns:
        None: login 用 role を保存して完了し, 呼び出し側へ値を返さない.

    Notes:
        `TestClient` の context に入った後にだけ呼び出す.
    """
    seed_role_sync(app, _DEFAULT_ROLE)


def _seed_default_channels(app: Starlette) -> None:
    """Login response で表示する channel と role override を保存する.

    Args:
        app (Starlette): lifespan 済みの test application.

    Returns:
        None: login 用 channel data を保存して完了し, 呼び出し側へ値を返さない.
    """

    async def _seed() -> None:
        """Channel と Default role 向け override を非同期で保存する.

        Returns:
            None: channel data を保存して完了し, 呼び出し側へ値を返さない.
        """
        channel = await seed_channel(app, make_channel(id=0))
        await seed_channel_override(
            app,
            make_channel_role_override(
                channel_id=channel.id,
                role_id=_DEFAULT_ROLE.id,
            ),
        )

    asyncio.run(_seed())


def _seed_test_data(app: Starlette) -> None:
    """成功する login test に必要な role と channel を保存する.

    Args:
        app (Starlette): lifespan 済みの test application.

    Returns:
        None: login に必要な test data を保存して完了し, 呼び出し側へ値を返さない.
    """
    _seed_default_role(app)
    _seed_default_channels(app)


def _registration_form(
    *,
    username: str = _TEST_USERNAME,
    email: str = _TEST_EMAIL,
    password: str = _TEST_PASSWORD,
) -> dict[str, str]:
    """Stable registration endpoint 用の form data を組み立てる.

    Args:
        username (str): `user[username]` に設定する account name.
        email (str): `user[user_email]` に設定する email address.
        password (str): `user[password]` に設定する plaintext password.

    Returns:
        dict[str, str]: account 作成を示す `check=0` を含む form data.
    """
    return {
        "user[username]": username,
        "user[user_email]": email,
        "user[password]": password,
        "check": "0",
    }


def _login_body(
    *,
    username: str = _TEST_USERNAME,
    password_md5: str = _TEST_PASSWORD_MD5,
    client_info: str = _TEST_CLIENT_INFO,
) -> bytes:
    """Osu! stable format の raw login request body を組み立てる.

    Args:
        username (str): login する account name.
        password_md5 (str): hex 形式の password MD5.
        client_info (str): stable client が送る version と capability 情報.

    Returns:
        bytes: 改行区切りの username, password MD5, client info を含む request body.
    """
    return f"{username}\n{password_md5}\n{client_info}\n".encode()


def _register_user(client: TestClient) -> None:
    """既定の test user を registration endpoint へ登録する.

    Args:
        client (TestClient): registration request を送信する test client.

    Returns:
        None: successful registration を検証して完了し, 呼び出し側へ値を返さない.
    """
    resp = client.post("/web/users", data=_registration_form())
    assert resp.status_code == HTTPStatus.OK, f"Registration failed: {resp.content!r}"


def _parse_packets(body: bytes) -> list[tuple[int, bytes]]:
    """連結された S2C packet stream を packet ID と payload の組へ分解する.

    Args:
        body (bytes): Bancho response body 全体.

    Returns:
        list[tuple[int, bytes]]: 完全な packet ごとの packet ID と payload の組.

    Notes:
        末尾に不完全な header または payload がある場合は, その packet を結果へ含めない.
    """
    packets: list[tuple[int, bytes]] = []
    offset = 0
    while offset + _PACKET_HEADER_SIZE <= len(body):
        packet_id: int = struct.unpack_from("<H", body, offset)[0]  # pyright: ignore[reportAny]  # struct.unpack_from returns tuple[Any, ...]
        content_len: int = struct.unpack_from("<I", body, offset + 3)[0]  # pyright: ignore[reportAny]  # struct.unpack_from returns tuple[Any, ...]
        content_start = offset + _PACKET_HEADER_SIZE
        content_end: int = content_start + content_len
        if content_end > len(body):
            break
        content = body[content_start:content_end]
        packets.append((packet_id, content))
        offset = content_end
    return packets


def _find_packet(
    packets: list[tuple[int, bytes]],
    packet_id: int,
) -> bytes | None:
    """指定した packet ID に一致する最初の payload を返す.

    Args:
        packets (list[tuple[int, bytes]]): packet ID と payload の順序付き組.
        packet_id (int): 検索する packet ID.

    Returns:
        bytes | None: 一致した packet の payload. 一致しない場合は `None`.
    """
    for pid, content in packets:
        if pid == packet_id:
            return content
    return None


# ── Test: Bancho routing ────────────────────────────────────────────────


class TestBanchoRouting:
    """stable client host による Bancho POST routing 契約を検証する."""

    def test_numbered_and_ce_hosts_reach_bancho_endpoint(self) -> None:
        """番号付き `cN` と `ce` host が Bancho endpoint へ到達する契約を検証する.

        3 種の stable client host から root へ POST し, すべてが HTTP 200 を返すことを確認する.

        Returns:
            None: routing response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                for url in (
                    "http://c4.athena.localhost/",
                    "http://c6.athena.localhost/",
                    "http://ce.athena.localhost/",
                ):
                    response = client.post(url)
                    assert response.status_code == HTTPStatus.OK

    def test_post_root_requires_bancho_host(self) -> None:
        """Bancho host ではない root POST を path fallback として扱わない契約を検証する.

        host を指定しない root POST が HTTP 405 になり, Bancho route へ到達しないことを確認する.

        Returns:
            None: 拒否 response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/")
                assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


# ── Test: Full registration + login flow ─────────────────────────────────


class TestRegisterAndLoginFlow:
    """registration 後の Bancho login response 契約を検証する."""

    def test_register_then_login_returns_cho_token(self) -> None:
        """Account 作成後の login が `cho-token` header を返す契約を検証する.

        `check=0` の registration を成功させた後に credentials を送信し, 空でない token を確認する.

        Returns:
            None: login header を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(_BANCHO_URL, content=_login_body())

                assert response.status_code == HTTPStatus.OK
                assert "cho-token" in response.headers
                assert len(response.headers["cho-token"]) > 0

    def test_register_then_login_returns_packet_stream(self) -> None:
        """Account 作成後の login が空でない S2C packet stream を返す契約を検証する.

        registration 済み user の login response body が packet header より長いことを確認する.

        Returns:
            None: packet stream を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(_BANCHO_URL, content=_login_body())

                assert response.status_code == HTTPStatus.OK
                assert len(response.content) > _PACKET_HEADER_SIZE

    def test_register_then_login_accepts_uppercase_password_md5(self) -> None:
        """Stable login が uppercase password MD5 を受け入れる契約を検証する.

        registration 済み user の password MD5 を uppercase hex で送信する.
        token が発行されることを確認する.

        Returns:
            None: case-insensitive authentication を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(
                    _BANCHO_URL,
                    content=_login_body(password_md5=_TEST_PASSWORD_MD5.upper()),
                )

                assert response.status_code == HTTPStatus.OK
                assert "cho-token" in response.headers


# ── Test: Login success packet verification ──────────────────────────────


class TestLoginSuccessPackets:
    """成功する login response の S2C packet stream 契約を検証する."""

    def test_login_reply_contains_positive_user_id(self) -> None:
        """成功する login の先頭 packet が正の user ID を持つ `LOGIN_REPLY` になる契約を検証する.

        registration 済み user の response を分解する.
        最初の payload を signed integer として確認する.

        Returns:
            None: login reply の user ID を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(_BANCHO_URL, content=_login_body())
                packets = _parse_packets(response.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id > 0

    def test_packet_stream_contains_protocol_version(self) -> None:
        """成功する login response が正の protocol version packet を含む契約を検証する.

        response stream から `PROTOCOL_VERSION` を探す.
        payload の version が正であることを確認する.

        Returns:
            None: protocol version packet を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(_BANCHO_URL, content=_login_body())
                packets = _parse_packets(response.content)

                content = _find_packet(packets, _PROTOCOL_VERSION_ID)
                assert content is not None, "protocol_version packet not found in stream"
                version: int = struct.unpack("<i", content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert version > 0

    def test_packet_stream_contains_login_permissions(self) -> None:
        """成功する login response が `LOGIN_PERMISSIONS` packet を含む契約を検証する.

        registration 済み user の response stream から permission packet を取得する.
        packet を取得できることを確認する.

        Returns:
            None: permission packet の存在を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(_BANCHO_URL, content=_login_body())
                packets = _parse_packets(response.content)

                content = _find_packet(packets, _LOGIN_PERMISSIONS_ID)
                assert content is not None, "login_permissions packet not found in stream"

    def test_packet_stream_has_expected_packet_count(self) -> None:
        """成功する login response が最低限必要な数の S2C packet を含む契約を検証する.

        registration 済み user の response stream を分解し, 10 以上の packet があることを確認する.

        Returns:
            None: packet 数を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                response = client.post(_BANCHO_URL, content=_login_body())
                packets = _parse_packets(response.content)

                assert len(packets) >= _EXPECTED_MIN_PACKETS, (
                    f"Expected at least {_EXPECTED_MIN_PACKETS} packets, got {len(packets)}"
                )


# ── Test: Polling stub ───────────────────────────────────────────────────


class TestPollingStub:
    """有効な session token による polling の基本契約を検証する."""

    def test_polling_with_valid_token_returns_empty_body(self) -> None:
        """Packet がない polling が HTTP 200 と空 response body を返す契約を検証する.

        login で発行された `osu-token` を送信し, polling queue が空の場合の response を確認する.

        Returns:
            None: polling response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                login_resp = client.post(_BANCHO_URL, content=_login_body())
                token = login_resp.headers["cho-token"]

                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": token})

                assert poll_resp.status_code == HTTPStatus.OK
                assert poll_resp.content == b""


class TestPresenceBroadcast:
    """login 時の live presence が polling queue で配送される契約を検証する."""

    def test_second_login_enqueues_user_presence_for_existing_online_user(self) -> None:
        """後から login した user の `USER_PRESENCE` を既存 online user が受信する契約を検証する.

        先に login した user の queue を空にしてから 2 人目を login させる.
        次の polling response を確認する.

        Returns:
            None: presence payload の user ID を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)
                second_register = client.post(
                    "/web/users",
                    data=_registration_form(
                        username="SecondUser",
                        email="second@example.com",
                    ),
                )
                assert second_register.status_code == HTTPStatus.OK

                login_a = client.post(_BANCHO_URL, content=_login_body())
                assert login_a.status_code == HTTPStatus.OK
                token_a = login_a.headers["cho-token"]

                first_poll = client.post(_BANCHO_URL, headers={"osu-token": token_a})
                assert first_poll.status_code == HTTPStatus.OK
                assert first_poll.content == b""

                login_b = client.post(
                    _BANCHO_URL,
                    content=_login_body(username="SecondUser"),
                )
                assert login_b.status_code == HTTPStatus.OK
                login_b_reply = _find_packet(
                    _parse_packets(login_b.content),
                    _LOGIN_REPLY_ID,
                )
                assert login_b_reply is not None
                user_b_id = cast("int", struct.unpack_from("<i", login_b_reply, 0)[0])

                second_poll = client.post(_BANCHO_URL, headers={"osu-token": token_a})
                assert second_poll.status_code == HTTPStatus.OK
                presence_packets = [
                    content
                    for packet_id, content in _parse_packets(second_poll.content)
                    if packet_id == ServerPacketID.USER_PRESENCE
                ]

                assert any(
                    cast("int", struct.unpack_from("<i", packet, 0)[0]) == user_b_id
                    for packet in presence_packets
                )


# ── Test: Re-login ───────────────────────────────────────────────────────


class TestReLogin:
    """re-login が session token を置換する契約を検証する."""

    def test_relogin_returns_new_token(self) -> None:
        """同一 user の 2 回目 login が別の `cho-token` を発行する契約を検証する.

        registration 後に同じ credentials で 2 回 login し, token 値が異なることを確認する.

        Returns:
            None: token の置換を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                resp1 = client.post(_BANCHO_URL, content=_login_body())
                token1 = resp1.headers["cho-token"]

                resp2 = client.post(_BANCHO_URL, content=_login_body())
                token2 = resp2.headers["cho-token"]

                assert token1 != token2

    def test_old_token_polling_fails_after_relogin(self) -> None:
        """re-login 後の古い token による polling が authentication failure になる契約を検証する.

        1 回目の token を保持して 2 回目の login を行う.
        古い token の response が `LOGIN_REPLY(-1)` になることを確認する.

        Returns:
            None: 古い token の拒否を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                resp1 = client.post(_BANCHO_URL, content=_login_body())
                old_token = resp1.headers["cho-token"]

                # Re-login
                _ = client.post(_BANCHO_URL, content=_login_body())

                # Poll with old token — should get authentication failure
                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": old_token})
                packets = _parse_packets(poll_resp.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id == _AUTH_FAILED_USER_ID

    def test_new_token_polling_succeeds_after_relogin(self) -> None:
        """re-login 後の新しい token による polling が成功する契約を検証する.

        2 回目の login で取得した token を送信し, HTTP 200 と空 response body を確認する.

        Returns:
            None: 新しい token の polling を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                _ = client.post(_BANCHO_URL, content=_login_body())

                resp2 = client.post(_BANCHO_URL, content=_login_body())
                new_token = resp2.headers["cho-token"]

                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": new_token})

                assert poll_resp.status_code == HTTPStatus.OK
                assert poll_resp.content == b""


# ── Test: Authentication failure ─────────────────────────────────────────


class TestAuthenticationFailure:
    """無効な credentials による login failure の response 契約を検証する."""

    def test_unregistered_user_returns_auth_failed(self) -> None:
        """未登録 user の login が `LOGIN_REPLY(-1)` を返す契約を検証する.

        role と user data を保存しない application へ未知の username を送信する.
        authentication failure を確認する.

        Returns:
            None: 未登録 user の failure response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    _BANCHO_URL,
                    content=_login_body(username="NonExistentUser"),
                )

                assert response.status_code == HTTPStatus.OK
                packets = _parse_packets(response.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id == _AUTH_FAILED_USER_ID

    def test_wrong_password_returns_auth_failed(self) -> None:
        """誤った password の login が `LOGIN_REPLY(-1)` を返す契約を検証する.

        登録済み username と異なる password MD5 を送信し, authentication failure を確認する.

        Returns:
            None: 誤った password の failure response を検証して完了し, 呼び出し側へ値を返さない.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_test_data(app)
                _register_user(client)

                wrong_md5 = hashlib.md5(b"wrongpassword").hexdigest()
                response = client.post(
                    _BANCHO_URL,
                    content=_login_body(password_md5=wrong_md5),
                )

                assert response.status_code == HTTPStatus.OK
                packets = _parse_packets(response.content)

                assert len(packets) > 0
                first_id, first_content = packets[0]
                assert first_id == _LOGIN_REPLY_ID
                user_id: int = struct.unpack("<i", first_content)[0]  # pyright: ignore[reportAny]  # struct.unpack returns tuple[Any, ...]
                assert user_id == _AUTH_FAILED_USER_ID
