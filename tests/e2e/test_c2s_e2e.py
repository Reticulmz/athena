"""C2S packet handlerのHTTP dispatchとexception isolationのE2E contractを検証する."""

from __future__ import annotations

import hashlib
import os
import struct
from contextlib import contextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from starlette.testclient import TestClient

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID, ServerPacketID
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency_sync
from tests.support.persistence import seed_role_sync

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

# ── Constants ────────────────────────────────────────────────────────────

_USER_A_USERNAME = "PlayerA"
_USER_A_EMAIL = "playera@example.com"
_USER_B_USERNAME = "PlayerB"
_USER_B_EMAIL = "playerb@example.com"

_TEST_PASSWORD = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD.encode()).hexdigest()
_TEST_CLIENT_INFO = "b20240101.1|9|1|abc:def:ghi:jkl:mno|0"

_PACKET_HEADER_SIZE = 7  # 2 (id) + 1 (compression) + 4 (content_length)
_BANCHO_URL = "http://c.athena.localhost/"

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED,
    position=0,
)


# ── Helpers ──────────────────────────────────────────────────────────────


@contextmanager
def _test_env() -> Generator[None]:
    """block実行中だけE2E test用environment variableを設定する.

    Yields:
        None: ENVIRONMENT=testとAthena domainが設定された実行scope.
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
    """command-side in-memory persistenceへDefault roleをseedする.

    Args:
        app (Starlette): DI containerを保持するtest application.

    Returns:
        None: login前提となるDefault roleを保存し, 呼び出し側へ値を返さずに完了する.
    """
    seed_role_sync(app, _DEFAULT_ROLE)


def _login_body(
    *,
    username: str,
    password_md5: str = _TEST_PASSWORD_MD5,
    client_info: str = _TEST_CLIENT_INFO,
) -> bytes:
    """Osu! stable formatのraw login request bodyを作る.

    Args:
        username (str): loginするuser名.
        password_md5 (str): passwordのMD5 digest.
        client_info (str): stable client information field.

    Returns:
        bytes: bancho login endpointへ送るnewline区切りbody.
    """
    return f"{username}\n{password_md5}\n{client_info}\n".encode()


def _registration_form(*, username: str, email: str) -> dict[str, str]:
    """account作成を要求するlegacy registration formを作る.

    Args:
        username (str): 作成するuser名.
        email (str): 作成するemail address.

    Returns:
        dict[str, str]: check=0を含むlegacy endpoint用form field mapping.
    """
    return {
        "user[username]": username,
        "user[user_email]": email,
        "user[password]": _TEST_PASSWORD,
        "check": "0",
    }


def _register_user(client: TestClient, *, username: str, email: str) -> None:
    """Legacy registration endpointでtest userを作成する.

    Args:
        client (TestClient): requestを送るapplication client.
        username (str): 作成するuser名.
        email (str): 作成するemail address.

    Returns:
        None: HTTP 200のaccount作成をassertし, 呼び出し側へ値を返さずに完了する.
    """
    resp = client.post("/web/users", data=_registration_form(username=username, email=email))
    assert resp.status_code == HTTPStatus.OK, f"Registration failed: {resp.content!r}"


def _login_user(client: TestClient, *, username: str) -> str:
    """Stable loginを完了し, 初期packet queueをdrainしてcho-tokenを返す.

    Args:
        client (TestClient): login requestを送るapplication client.
        username (str): loginするuser名.

    Returns:
        str: 後続bancho requestのosu-token headerへ設定するcho-token.
    """
    resp = client.post(_BANCHO_URL, content=_login_body(username=username))
    assert resp.status_code == HTTPStatus.OK
    token = resp.headers["cho-token"]
    assert len(token) > 0

    # Drain the initial login packet queue (login response packets may be
    # enqueued for this user; the first poll clears them).
    drain_resp = client.post(_BANCHO_URL, headers={"osu-token": token})
    assert drain_resp.status_code == HTTPStatus.OK

    return token


def _build_c2s_packet(packet_id: int, payload: bytes = b"") -> bytes:
    """7 byte headerとpayloadからraw C2S packetを作る.

    Args:
        packet_id (int): C2S packet識別子.
        payload (bytes): header後に連結するpacket payload.

    Returns:
        bytes: little-endian headerを持つwire packet.
    """
    header = struct.pack("<HBI", packet_id, 0, len(payload))
    return header + payload


def _parse_s2c_packets(body: bytes) -> list[tuple[int, bytes]]:
    """連結されたS2C packet streamをpacket idとcontentのpairへ分解する.

    Args:
        body (bytes): bancho response bodyのpacket stream.

    Returns:
        list[tuple[int, bytes]]: 完全なheaderとcontentを持つpacket pair一覧.
    """
    packets: list[tuple[int, bytes]] = []
    offset = 0
    while offset + _PACKET_HEADER_SIZE <= len(body):
        unpacked_id = struct.unpack_from("<H", body, offset)
        packet_id = cast("int", unpacked_id[0])
        unpacked_len = struct.unpack_from("<I", body, offset + 3)
        content_len = cast("int", unpacked_len[0])
        content_start = offset + _PACKET_HEADER_SIZE
        content_end = content_start + content_len
        if content_end > len(body):
            break
        content = body[content_start:content_end]
        packets.append((packet_id, content))
        offset = content_end
    return packets


def _find_packets(
    packets: list[tuple[int, bytes]],
    packet_id: int,
) -> list[bytes]:
    """指定packet idに一致するS2C packet contentを抽出する.

    Args:
        packets (list[tuple[int, bytes]]): parse済みS2C packet一覧.
        packet_id (int): 抽出するpacket識別子.

    Returns:
        list[bytes]: packet idが一致するcontent一覧.
    """
    return [content for pid, content in packets if pid == packet_id]


# ── Test: EXIT → USER_QUIT broadcast ────────────────────────────────────


class TestExitUserQuitBroadcast:
    """EXIT送信後に他userのpolling responseへUSER_QUITをbroadcastするcontractを検証する."""

    def test_exit_broadcasts_user_quit_to_other_user(self) -> None:
        """EXIT C2S packetが他online userへUSER_QUIT S2C packetをenqueueすることを検証する.

        Returns:
            None: 他userのpolling responseのpacket idとuser idを検証し,
                呼び出し側へ値を返さずに完了する.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                # Register and login two users
                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                _register_user(client, username=_USER_B_USERNAME, email=_USER_B_EMAIL)
                token_a = _login_user(client, username=_USER_A_USERNAME)
                token_b = _login_user(client, username=_USER_B_USERNAME)

                # User A sends EXIT packet
                exit_packet = _build_c2s_packet(ClientPacketID.EXIT)
                exit_resp = client.post(
                    _BANCHO_URL,
                    content=exit_packet,
                    headers={"osu-token": token_a},
                )
                assert exit_resp.status_code == HTTPStatus.OK

                # User B polls — should receive USER_QUIT for user A
                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": token_b})
                assert poll_resp.status_code == HTTPStatus.OK

                packets = _parse_s2c_packets(poll_resp.content)
                quit_contents = _find_packets(packets, int(ServerPacketID.USER_QUIT))

                assert len(quit_contents) >= 1, (
                    f"Expected USER_QUIT packet in poll response, "
                    f"got packet IDs: {[pid for pid, _ in packets]}"
                )

                # USER_QUIT payload is the disconnected user's ID as int32 LE
                unpacked_uid = struct.unpack("<i", quit_contents[0])
                quit_user_id = cast("int", unpacked_uid[0])
                assert quit_user_id > 0, "USER_QUIT should contain a positive user_id"

    def test_exit_does_not_enqueue_user_quit_for_self(self) -> None:
        """EXITしたsole online userが自身のUSER_QUIT通知を受けないことを検証する.

        Returns:
            None: EXIT responseにUSER_QUITが含まれないことを検証し,
                呼び出し側へ値を返さずに完了する.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token_a = _login_user(client, username=_USER_A_USERNAME)

                # User A sends EXIT — response should not contain USER_QUIT for self.
                # After EXIT, the session is deleted, so the dequeue_all runs on
                # the (now-deleted) user. The response may be empty or contain
                # only other queued packets, but not a USER_QUIT for user A.
                exit_packet = _build_c2s_packet(ClientPacketID.EXIT)
                exit_resp = client.post(
                    _BANCHO_URL,
                    content=exit_packet,
                    headers={"osu-token": token_a},
                )
                assert exit_resp.status_code == HTTPStatus.OK

                # The EXIT response should not contain a USER_QUIT for the
                # exiting user. Parse whatever was returned.
                packets = _parse_s2c_packets(exit_resp.content)
                quit_contents = _find_packets(packets, int(ServerPacketID.USER_QUIT))
                # There should be no USER_QUIT packets (no other users to notify about)
                assert len(quit_contents) == 0, (
                    "Exiting user (sole online user) should not receive any USER_QUIT packets"
                )


# ── Test: PONG acceptance ────────────────────────────────────────────────


class TestPongAcceptance:
    """PONG C2S packetをerrorなく受理するcontractを検証する."""

    def test_pong_returns_empty_response(self) -> None:
        """PONG C2S packetがHTTP 200とempty S2C responseを返すことを検証する.

        Returns:
            None: no-op PONGのresponse statusとbodyを検証し, 呼び出し側へ値を返さずに完了する.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token = _login_user(client, username=_USER_A_USERNAME)

                # Send PONG packet
                pong_packet = _build_c2s_packet(ClientPacketID.PONG)
                resp = client.post(
                    _BANCHO_URL,
                    content=pong_packet,
                    headers={"osu-token": token},
                )

                assert resp.status_code == HTTPStatus.OK
                # PONG is a no-op — no S2C packets should be generated
                assert resp.content == b""

    def test_multiple_pongs_accepted(self) -> None:
        """1 request内の複数PONG packetをすべて受理することを検証する.

        Returns:
            None: 複数PONGのHTTP 200とempty responseを検証し, 呼び出し側へ値を返さずに完了する.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token = _login_user(client, username=_USER_A_USERNAME)

                # Send 3 concatenated PONG packets
                body = (
                    _build_c2s_packet(ClientPacketID.PONG)
                    + _build_c2s_packet(ClientPacketID.PONG)
                    + _build_c2s_packet(ClientPacketID.PONG)
                )
                resp = client.post(
                    _BANCHO_URL,
                    content=body,
                    headers={"osu-token": token},
                )

                assert resp.status_code == HTTPStatus.OK
                assert resp.content == b""


# ── Test: Exception isolation ────────────────────────────────────────────


class TestExceptionIsolation:
    """失敗したpacket handlerが後続packetの処理を止めないcontractを検証する."""

    def test_invalid_packet_followed_by_pong_still_processes_pong(self) -> None:
        """未登録packetとPONGを同一requestで送って後続PONGが処理されることを検証する.

        Returns:
            None: dispatcherが未登録packetをskipしてHTTP 200を返すことを検証し,
                呼び出し側へ値を返さずに完了する.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                token = _login_user(client, username=_USER_A_USERNAME)

                # Build a packet with a valid but unregistered ClientPacketID
                # (SEND_MESSAGE = 1 has no handler registered yet) plus garbage payload
                # followed by a valid PONG packet.
                bad_packet = _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\xff\xfe\xfd")
                pong_packet = _build_c2s_packet(ClientPacketID.PONG)
                body = bad_packet + pong_packet

                resp = client.post(
                    _BANCHO_URL,
                    content=body,
                    headers={"osu-token": token},
                )

                # Request should succeed — exception isolation keeps processing
                assert resp.status_code == HTTPStatus.OK
                # PONG produces no S2C output, and unregistered packet is skipped
                assert resp.content == b""

    def test_exception_in_handler_does_not_break_subsequent_packets(self) -> None:
        """送出するhandler後も後続EXIT packetが処理されることを検証する.

        意図的failure handlerとEXITを同一requestで送信し,
        他userがUSER_QUITを受信することを確認する.

        Returns:
            None: packet単位exception isolationのobservable broadcastを検証し,
                呼び出し側へ値を返さずに完了する.
        """
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                _seed_default_role(app)

                _register_user(client, username=_USER_A_USERNAME, email=_USER_A_EMAIL)
                _register_user(client, username=_USER_B_USERNAME, email=_USER_B_EMAIL)
                token_a = _login_user(client, username=_USER_A_USERNAME)
                token_b = _login_user(client, username=_USER_B_USERNAME)

                # Register a handler that always raises for a specific packet ID.
                # Use BEATMAP_INFO (68) — unlikely to have a real handler.
                dispatcher = resolve_dependency_sync(app, PacketDispatcher)

                @dispatcher.register(ClientPacketID.BEATMAP_INFO)
                async def _boom(_payload: bytes, _user_id: int) -> None:
                    """packet単位のexception isolationを起動する意図的なfailure handler.

                    Args:
                        _payload (bytes): dispatcherが渡すpacket payload.
                        _user_id (int): packetを送信したuser識別子.

                    Returns:
                        None: 常にRuntimeErrorを送出し, 呼び出し側へ値を返さずに完了しない.

                    Raises:
                        RuntimeError: exception isolationを検証するため常に送出する.
                    """
                    msg = "intentional test explosion"
                    raise RuntimeError(msg)

                _ = _boom

                # Send: BEATMAP_INFO (will raise) + EXIT (should still process)
                bad_packet = _build_c2s_packet(ClientPacketID.BEATMAP_INFO, b"\x00")
                exit_packet = _build_c2s_packet(ClientPacketID.EXIT)
                body = bad_packet + exit_packet

                resp = client.post(
                    _BANCHO_URL,
                    content=body,
                    headers={"osu-token": token_a},
                )

                assert resp.status_code == HTTPStatus.OK

                # Verify EXIT was still processed despite BEATMAP_INFO failure:
                # User B should see USER_QUIT for user A
                poll_resp = client.post(_BANCHO_URL, headers={"osu-token": token_b})
                assert poll_resp.status_code == HTTPStatus.OK

                packets = _parse_s2c_packets(poll_resp.content)
                quit_contents = _find_packets(packets, int(ServerPacketID.USER_QUIT))

                assert len(quit_contents) >= 1, (
                    f"EXIT should have been processed despite BEATMAP_INFO error; "
                    f"got packet IDs: {[pid for pid, _ in packets]}"
                )
