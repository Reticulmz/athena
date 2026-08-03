"""Chat C2SのHTTP end-to-end契約を検証する.

ログインからpollとC2S dispatchを経てS2C packetを受信する流れを確認する.
DIに登録されたhandlerを用いchannelとprivate messageの可視結果を検証する.
"""

from __future__ import annotations

import hashlib
import os
import struct
from http import HTTPStatus
from typing import TYPE_CHECKING

from caterpillar.model import pack
from starlette.testclient import TestClient

from osu_server.domain.identity.authentication import RegistrationForm
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.transports.stable.bancho.protocol.c2s import (
    message_payload as c2s_message_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.s2c.chat import (
    channel_join_success,
    send_message,
)
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    channel_available,
    channel_available_autojoin,
    channel_info_complete,
    user_presence,
    user_presence_bundle,
)
from osu_server.transports.stable.bancho.protocol.types import BanchoString
from tests.factories.domain import make_channel, make_channel_role_override
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.persistence import seed_channel, seed_channel_override, seed_role

if TYPE_CHECKING:
    from starlette.applications import Starlette

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_CLIENT_INFO = "20231111|9|1|hash1:hash2:hash3|0"
_BANCHO_URL = "http://c.athena.localhost/"
_STABLE_CLIENT_EMPTY_SENDER = ""
_STABLE_CLIENT_EMPTY_SENDER_ID = 0

_DEFAULT_ROLE = Role(
    id=1,
    name="Default",
    permissions=(
        Privileges.NORMAL
        | Privileges.VERIFIED
        | Privileges.UNRESTRICTED
        | Privileges.BYPASS_CHANNEL_ACL
    ),
    position=0,
)

# Module-level env defaults for test DI container
_ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
_ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")


# -- App / DI helpers --------------------------------------------------------


def _make_test_app() -> Starlette:
    """BanchoEndpointを含むDI構成済みのtest appを生成する.

    Returns:
        Starlette: test環境とathena.localhost domainを設定したapplication.
    """
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    return create_app()


async def _seed_default_role(app: Starlette) -> None:
    """Default roleをcommand側のin-memory persistenceへ登録する.

    Args:
        app (Starlette): dependencyを解決するlifespan開始済みapplication.

    Returns:
        None: roleの登録を完了して値を返さない.
    """
    await seed_role(app, _DEFAULT_ROLE)


async def _seed_channels(app: Starlette) -> None:
    """channelとrole overrideをcommand側のin-memory persistenceへ登録する.

    Args:
        app (Starlette): dependencyを解決するlifespan開始済みapplication.

    Returns:
        None: #osuと#announceの可視性設定を登録して値を返さない.
    """
    osu_channel = await seed_channel(
        app,
        make_channel(name="#osu", topic="General discussion", auto_join=True),
    )
    announce_channel = await seed_channel(
        app,
        make_channel(name="#announce", topic="Announcements", auto_join=False),
    )
    await seed_channel_override(
        app,
        make_channel_role_override(
            channel_id=osu_channel.id,
            role_id=_DEFAULT_ROLE.id,
        ),
    )
    await seed_channel_override(
        app,
        make_channel_role_override(
            channel_id=announce_channel.id,
            role_id=_DEFAULT_ROLE.id,
            can_read=True,
            can_write=False,
        ),
    )


async def _resolve_services(
    app: Starlette,
) -> tuple[AuthService, SessionStore, ChannelStateStore]:
    """testで利用するserviceとstate storeをcontainerから解決する.

    Args:
        app (Starlette): dependencyを解決するlifespan開始済みapplication.

    Returns:
        tuple[AuthService, SessionStore, ChannelStateStore]: roleとchannelをseed済みのservice群.
    """
    await _seed_default_role(app)
    await _seed_channels(app)
    return (
        await resolve_dependency(app, AuthService),
        await resolve_dependency(app, SessionStore),
        await resolve_dependency(app, ChannelStateStore),
    )


# -- Protocol helpers --------------------------------------------------------


def _login_body(username: str) -> bytes:
    """Stable login request用のbodyを構築する.

    Args:
        username (str): loginする利用者名.

    Returns:
        bytes: 利用者名と固定credential/client情報を改行で連結したrequest body.
    """
    return f"{username}\n{_PASSWORD_MD5}\n{_CLIENT_INFO}\n".encode()


def _c2s_packet(packet_id: ClientPacketID, payload: bytes) -> bytes:
    """C2S packet headerとpayloadを連結する.

    Args:
        packet_id (ClientPacketID): headerへ設定するC2S packet ID.
        payload (bytes): headerの後ろへ連結するwire payload.

    Returns:
        bytes: compressionなしのBancho C2S packet.
    """
    return struct.pack("<HBI", packet_id.value, 0, len(payload)) + payload


def _channel_payload(channel_name: str) -> bytes:
    """channel名をBanchoString payloadへ符号化する.

    Args:
        channel_name (str): JOIN_CHANNELで指定するchannel名.

    Returns:
        bytes: CaterpillarでpackしたBanchoString payload.
    """
    return pack(channel_name, BanchoString)


def _stable_client_message_payload(*, content: str, target: str) -> bytes:
    """Stable client送信形式のMessage payloadを構築する.

    Args:
        content (str): channelまたはprivate messageへ送る本文.
        target (str): 宛先channel名または利用者名.

    Returns:
        bytes: 空senderとsender ID 0を持つC2S Message payload.
    """
    return c2s_message_payload(
        sender=_STABLE_CLIENT_EMPTY_SENDER,
        content=content,
        target=target,
        sender_id=_STABLE_CLIENT_EMPTY_SENDER_ID,
    )


async def _register_user(auth_service: AuthService, username: str, email: str) -> None:
    """test利用者を登録して成功結果を検証する.

    Args:
        auth_service (AuthService): registration commandを実行するservice.
        username (str): 登録する利用者名.
        email (str): 登録するemail address.

    Returns:
        None: registration成功を検証して値を返さない.

    Raises:
        AssertionError: registration resultが成功を示さない場合.
    """
    result = await auth_service.register(
        RegistrationForm(username=username, email=email, password=_PASSWORD),
    )
    assert result.success is True


def _login(client: TestClient, username: str) -> str:
    """Stable loginを実行して発行されたsession tokenを取得する.

    Args:
        client (TestClient): Bancho endpointへrequestを送るtest client.
        username (str): loginする登録済み利用者名.

    Returns:
        str: successful login responseのcho-token header.

    Raises:
        AssertionError: login responseがHTTP 200でない場合.
    """
    response = client.post(_BANCHO_URL, content=_login_body(username))
    assert response.status_code == HTTPStatus.OK
    return response.headers["cho-token"]


def _poll(client: TestClient, token: str, content: bytes = b"") -> bytes:
    """Session tokenでBancho poll requestを送信する.

    Args:
        client (TestClient): Bancho endpointへrequestを送るtest client.
        token (str): osu-token headerへ設定する有効なsession token.
        content (bytes): poll requestに含める任意のC2S packet stream.

    Returns:
        bytes: HTTP 200 responseに含まれるS2C packet stream.

    Raises:
        AssertionError: poll responseがHTTP 200でない場合.
    """
    response = client.post(_BANCHO_URL, headers={"osu-token": token}, content=content)
    assert response.status_code == HTTPStatus.OK
    return response.content


async def _user_id_for_token(session_store: SessionStore, token: str) -> int:
    """Session tokenに対応する利用者IDを取得する.

    Args:
        session_store (SessionStore): tokenから接続状態を取得するstore.
        token (str): 解決対象のsession token.

    Returns:
        int: tokenに紐付く接続利用者のID.

    Raises:
        AssertionError: tokenに対応するsessionが存在しない場合.
    """
    session = await session_store.get(token)
    assert session is not None
    return session.user_id


# ═══════════════════════════════════════════════════════════════════════════
# Channel Lifecycle
# ═══════════════════════════════════════════════════════════════════════════


class TestChannelLifecycleE2E:
    """channel参加後のC2S message delivery契約を検証する."""

    async def test_http_join_then_channel_message_reaches_target_poll_response(
        self,
    ) -> None:
        """channel参加済みrecipientが次のpollでmessageを受信することを検証する.

        senderとtargetを登録して両者を#osuへ参加させる.
        観測結果としてsenderの送信pollは空でtargetの次のpollはS2C messageになる.

        Returns:
            None: channel message deliveryのHTTP可視結果を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")
            await _register_user(auth_service, "Target", "target@example.com")

            sender_token = _login(client, "Sender")
            target_token = _login(client, "Target")
            sender_id = await _user_id_for_token(session_store, sender_token)

            assert _poll(client, sender_token) == b""
            assert _poll(client, target_token) == b""

            target_join = _poll(
                client,
                target_token,
                _c2s_packet(ClientPacketID.JOIN_CHANNEL, _channel_payload("#osu")),
            )
            assert target_join == channel_join_success(channel_name="#osu")

            sender_join = _poll(
                client,
                sender_token,
                _c2s_packet(ClientPacketID.JOIN_CHANNEL, _channel_payload("#osu")),
            )
            assert sender_join == channel_join_success(channel_name="#osu")

            sender_response = _poll(
                client,
                sender_token,
                _c2s_packet(
                    ClientPacketID.SEND_MESSAGE,
                    _stable_client_message_payload(
                        content="hello channel",
                        target="#osu",
                    ),
                ),
            )
            assert sender_response == b""

            target_response = _poll(client, target_token)
            assert target_response == send_message(
                sender="Sender",
                content="hello channel",
                target="#osu",
                sender_id=sender_id,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Private Messages
# ═══════════════════════════════════════════════════════════════════════════


class TestPrivateMessageE2E:
    """private messageのC2S delivery契約を検証する."""

    async def test_http_private_message_reaches_target_poll_response(self) -> None:
        """Online targetが次のpollでprivate messageを受信することを検証する.

        senderとtargetを登録してログイン後の初期packetをdrainする.
        観測結果としてsenderの送信pollは空でtargetの次のpollはS2C messageになる.

        Returns:
            None: private message deliveryのHTTP可視結果を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")
            await _register_user(auth_service, "Target", "target@example.com")

            sender_token = _login(client, "Sender")
            target_token = _login(client, "Target")
            sender_id = await _user_id_for_token(session_store, sender_token)

            assert _poll(client, sender_token) == b""
            assert _poll(client, target_token) == b""

            sender_response = _poll(
                client,
                sender_token,
                _c2s_packet(
                    ClientPacketID.SEND_PRIVATE_MESSAGE,
                    _stable_client_message_payload(
                        content="hello pm",
                        target="Target",
                    ),
                ),
            )
            assert sender_response == b""

            target_response = _poll(client, target_token)
            assert target_response == send_message(
                sender="Sender",
                content="hello pm",
                target="Target",
                sender_id=sender_id,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Login Channel List
# ═══════════════════════════════════════════════════════════════════════════


class TestLoginChannelListE2E:
    """login responseのchannel catalog構築契約を検証する."""

    async def test_login_response_contains_db_backed_channel_list(self) -> None:
        """Login responseがseed済みchannelの可視性と人数を含むことを検証する.

        #osuと#announceへ異なるmemberを追加して利用者をログインさせる.
        観測結果として両channel packetと#osuのautojoin packetと完了packetがstreamに入る.

        Returns:
            None: login channel catalogのS2C packet構成を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, channel_state = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")
            await channel_state.add_member("#osu", 101)
            await channel_state.add_member("#announce", 202)

            response = client.post(_BANCHO_URL, content=_login_body("Sender"))

        assert response.status_code == HTTPStatus.OK
        assert (
            channel_available(
                name="#osu",
                topic="General discussion",
                user_count=1,
            )
            in response.content
        )
        assert (
            channel_available(
                name="#announce",
                topic="Announcements",
                user_count=1,
            )
            in response.content
        )
        assert (
            channel_available_autojoin(
                name="#osu",
                topic="General discussion",
                user_count=1,
            )
            in response.content
        )
        assert channel_info_complete() in response.content


# ═══════════════════════════════════════════════════════════════════════════
# BanchoBot Identity E2E (Req 1.1, 1.2, 2.1, 2.2, 2.3, 3.1, 3.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestBanchoBotIdentityE2E:
    """login responseとcommand responseのBanchoBot identity契約を検証する."""

    async def test_login_response_contains_banchobot_presence(self) -> None:
        """Login responseがBanchoBotのUSER_PRESENCEを含むことを検証する.

        channelとroleをseedしたapplicationへ登録済み利用者がログインする.
        観測結果として固定IDと利用者名を持つBanchoBot presence packetがstreamに含まれる.

        Returns:
            None: login時のBanchoBot presence契約を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post(_BANCHO_URL, content=_login_body("Sender"))

        assert response.status_code == HTTPStatus.OK
        banchobot_presence = user_presence(
            user_id=BANCHO_BOT_IDENTITY.user_id,
            username=BANCHO_BOT_IDENTITY.username,
            timezone=24,
            country_id=0,
            permissions=0,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
        assert banchobot_presence in response.content

    async def test_login_response_contains_banchobot_bundle(self) -> None:
        """Login rosterがBanchoBotと接続利用者を重複なく含むことを検証する.

        登録済み利用者をログインして発行tokenから利用者IDを取得する.
        観測結果としてUSER_PRESENCE_BUNDLEはBanchoBot IDと利用者IDを一度ずつ含む.

        Returns:
            None: login rosterのidentity集合を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post(_BANCHO_URL, content=_login_body("Sender"))
            user_id = await _user_id_for_token(session_store, response.headers["cho-token"])

        assert response.status_code == HTTPStatus.OK
        roster_ids = list(dict.fromkeys([BANCHO_BOT_IDENTITY.user_id, user_id]))
        expected_bundle = user_presence_bundle(roster_ids)
        assert expected_bundle in response.content

    async def test_banchobot_presence_before_bundle(self) -> None:
        """BanchoBot presenceがroster bundleより先に出力されることを検証する.

        登録済み利用者をログインしてresponse stream内のpacket位置を比較する.
        観測結果としてUSER_PRESENCEの位置はUSER_PRESENCE_BUNDLEより小さい.

        Returns:
            None: clientがroster処理前にbot identityを得る順序を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post(_BANCHO_URL, content=_login_body("Sender"))

        assert response.status_code == HTTPStatus.OK
        banchobot_presence = user_presence(
            user_id=BANCHO_BOT_IDENTITY.user_id,
            username=BANCHO_BOT_IDENTITY.username,
            timezone=24,
            country_id=0,
            permissions=0,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
        bundle_marker = user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 2])
        presence_pos = response.content.index(banchobot_presence)
        bundle_pos = response.content.index(bundle_marker)
        assert presence_pos < bundle_pos, (
            "BanchoBot USER_PRESENCE must precede USER_PRESENCE_BUNDLE"
        )

    async def test_human_user_in_roster_with_banchobot(self) -> None:
        """Login rosterがBanchoBotと人間利用者の双方を保持することを検証する.

        登録済み利用者をログインしてresponse tokenから利用者IDを取得する.
        観測結果としてrosterには両IDが含まれ異なるIDなら要素数は2になる.

        Returns:
            None: botが人間利用者を置換しないroster契約を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, session_store, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            response = client.post(_BANCHO_URL, content=_login_body("Sender"))
            user_id = await _user_id_for_token(session_store, response.headers["cho-token"])

        assert response.status_code == HTTPStatus.OK
        roster_ids = list(dict.fromkeys([BANCHO_BOT_IDENTITY.user_id, user_id]))
        expected_bundle = user_presence_bundle(roster_ids)
        assert expected_bundle in response.content
        # BanchoBot is always present
        assert BANCHO_BOT_IDENTITY.user_id in roster_ids
        # Human user is never hidden or replaced by BanchoBot
        assert user_id in roster_ids
        if user_id != BANCHO_BOT_IDENTITY.user_id:
            assert len(roster_ids) == 2

    async def test_command_response_uses_banchobot_identity(self) -> None:
        """!help command responseがlogin rosterと同じBanchoBot identityを使うことを検証する.

        senderをログインして#osuへ参加させた後に!helpを送る.
        観測結果としてpoll responseに固定のBanchoBot sender IDと利用者名を持つmessageが入る.

        Returns:
            None: loginとcommand間のbot identity一貫性を検証して終了する.
        """
        app = _make_test_app()

        with TestClient(app) as client:
            auth_service, _, _ = await _resolve_services(app)
            await _register_user(auth_service, "Sender", "sender@example.com")

            token = _login(client, "Sender")
            assert _poll(client, token) == b""

            join_resp = _poll(
                client,
                token,
                _c2s_packet(
                    ClientPacketID.JOIN_CHANNEL,
                    _channel_payload("#osu"),
                ),
            )
            assert join_resp == channel_join_success(channel_name="#osu")

            poll_resp = _poll(
                client,
                token,
                _c2s_packet(
                    ClientPacketID.SEND_MESSAGE,
                    _stable_client_message_payload(
                        content="!help",
                        target="#osu",
                    ),
                ),
            )
            # The poll response contains BanchoBot's response
            banchobot_message = send_message(
                sender=BANCHO_BOT_IDENTITY.username,
                content="Available commands: !roll, !help",
                target="#osu",
                sender_id=BANCHO_BOT_IDENTITY.user_id,
            )
            assert banchobot_message in poll_resp
