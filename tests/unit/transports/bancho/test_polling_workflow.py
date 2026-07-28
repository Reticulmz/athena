"""Starlette非依存PollingWorkflowのC2S dispatchとS2C drain contractを検証する."""

from __future__ import annotations

import struct
from typing import cast, final, override

import structlog.testing

from osu_server.domain.identity.authentication import LoginResult
from osu_server.domain.identity.sessions import SessionData
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import login_reply
from osu_server.transports.stable.bancho.workflows import PollingWorkflow, PollingWorkflowInput

_TOKEN = "poll-token"
_USER_ID = 101
_SESSION_TTL = 123
_MAX_BODY_SIZE = 64
_QUEUED_A = b"queued-a"
_QUEUED_B = b"queued-b"


@final
class _RecordingSessionStore(InMemorySessionStore):
    """polling時のsession store呼び出し順を記録するInMemorySessionStore fakeを提供する.

    Attributes:
        operations (list[str]): getとrefreshの呼び出し順序.
    """

    operations: list[str]

    def __init__(self) -> None:
        """空のoperation記録を持つsession store fakeを初期化する."""
        super().__init__()
        self.operations = []

    @override
    async def get(self, token: str) -> SessionData | None:
        """Session lookupを記録して親storeへ委譲する.

        Args:
            token (str): lookupするpolling session token.

        Returns:
            SessionData | None: 親storeが返すsession data. token不在ならNone.
        """
        self.operations.append(f"session.get:{token}")
        return await super().get(token)

    @override
    async def refresh(self, token: str) -> bool:
        """Session TTL refreshを記録して親storeへ委譲する.

        Args:
            token (str): refreshするpolling session token.

        Returns:
            bool: 親storeがtokenをrefreshできた場合はTrue.
        """
        self.operations.append(f"session.refresh:{token}")
        return await super().refresh(token)


@final
class _RecordingPacketQueue(InMemoryPacketQueue):
    """queue drainとTTL refreshの順序を記録するInMemoryPacketQueue fakeを提供する.

    Attributes:
        operations (list[str]): dequeueとrefresh_ttlの呼び出し順序.
    """

    operations: list[str]

    def __init__(self) -> None:
        """空のoperation記録を持つpacket queue fakeを初期化する."""
        super().__init__()
        self.operations = []

    async def seed(self, user_id: int, *data: bytes) -> None:
        """polling前にqueueへpacketを投入してoperation記録を初期化する.

        Args:
            user_id (int): packetを所有するstable userのID.
            *data (bytes): drain前にqueueへ入れるS2C packet群.

        Returns:
            None: packet投入後にsetup operation記録を消去して完了する.
        """
        await super().refresh_ttl(user_id, _SESSION_TTL)
        await super().enqueue(user_id, *data)
        self.operations.clear()

    @override
    async def dequeue_all(self, user_id: int) -> bytes:
        """Queue drainを記録してparent queueから全packetを取り出す.

        Args:
            user_id (int): packet queueをdrainするstable userのID.

        Returns:
            bytes: parent queueが返す連結済みS2C packet stream.
        """
        self.operations.append(f"queue.dequeue:{user_id}")
        return await super().dequeue_all(user_id)

    @override
    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Queue TTL refreshを記録してparent queueへ委譲する.

        Args:
            user_id (int): TTLをrefreshするstable userのID.
            ttl (int): 設定するTTL秒数.

        Returns:
            None: parent queueのTTLをrefreshして完了し, 呼び出し側へ値を返さない.
        """
        self.operations.append(f"queue.refresh:{user_id}:{ttl}")
        await super().refresh_ttl(user_id, ttl)


@final
class _RecordingPacketDispatcher(PacketDispatcher):
    """C2S dispatch callと意図的handler failureを記録するPacketDispatcher fakeを提供する.

    Attributes:
        operations (list[str]): packet ID, payload, user IDを含むdispatch順序.
        calls (list[tuple[ClientPacketID, bytes, int]]): dispatch引数の構造化記録.
        failing_packets (set[ClientPacketID]): RuntimeErrorを送出するpacket ID集合.
    """

    operations: list[str]
    calls: list[tuple[ClientPacketID, bytes, int]]
    failing_packets: set[ClientPacketID]

    def __init__(self, *, failing_packets: set[ClientPacketID] | None = None) -> None:
        """optionalなhandler failure packet IDを設定する.

        Args:
            failing_packets (set[ClientPacketID] | None): dispatch時に失敗させるpacket ID集合.
                Noneなら全packetを成功扱いにする.
        """
        super().__init__()
        self.operations = []
        self.calls = []
        self.failing_packets = failing_packets or set()

    @override
    async def dispatch(self, packet_id: ClientPacketID, payload: bytes, user_id: int) -> None:
        """C2S dispatchを記録し,設定済みpacketではhandler failureを送出する.

        Args:
            packet_id (ClientPacketID): dispatchするC2S packetのID.
            payload (bytes): handlerへ渡す未加工payload.
            user_id (int): packetを送ったauthenticated userのID.

        Returns:
            None: 成功packetのdispatch記録を完了し, 呼び出し側へ値を返さない.

        Raises:
            RuntimeError: packet_idがfailing_packetsに含まれる場合.
        """
        self.operations.append(f"dispatch:{packet_id.name}:{payload.hex()}:{user_id}")
        self.calls.append((packet_id, payload, user_id))
        if packet_id in self.failing_packets:
            msg = f"intentional failure for {packet_id.name}"
            raise RuntimeError(msg)


def _session_data(user_id: int = _USER_ID) -> SessionData:
    """Polling test用の既定SessionDataを作る.

    Args:
        user_id (int): sessionへ設定するstable userのID.

    Returns:
        SessionData: PollingWorkflowが認証済みsessionとして利用するfixture data.
    """
    return SessionData(
        user_id=user_id,
        username="PollingUser",
        privileges=1,
        country="JP",
        osu_version="20231111",
        utc_offset=9,
        display_city=False,
        client_hashes="hash1:hash2:hash3",
        pm_private=False,
    )


def _build_c2s_packet(packet_id: ClientPacketID, payload: bytes = b"") -> bytes:
    """headerとpayloadを連結したC2S packetを構築する.

    Args:
        packet_id (ClientPacketID): headerへ書くC2S packet ID.
        payload (bytes): header後に連結する未加工payload.

    Returns:
        bytes: little-endian Bancho headerとpayloadを持つpacket.
    """
    return struct.pack("<HBI", int(packet_id), 0, len(payload)) + payload


def _make_workflow(
    *,
    session_store: _RecordingSessionStore | None = None,
    packet_queue: _RecordingPacketQueue | None = None,
    packet_dispatcher: _RecordingPacketDispatcher | None = None,
    max_request_body_size: int = _MAX_BODY_SIZE,
) -> tuple[
    PollingWorkflow,
    _RecordingSessionStore,
    _RecordingPacketQueue,
    _RecordingPacketDispatcher,
]:
    """Recording fakeを注入したPollingWorkflowと依存を構築する.

    Args:
        session_store (_RecordingSessionStore | None): optional session store fake.
        packet_queue (_RecordingPacketQueue | None): optional packet queue fake.
        packet_dispatcher (_RecordingPacketDispatcher | None): optional dispatcher fake.
        max_request_body_size (int): workflowが受け付ける最大request body size.

    Returns:
        tuple: workflowと実際に注入したrecording fake群.
    """
    store = session_store or _RecordingSessionStore()
    queue = packet_queue or _RecordingPacketQueue()
    dispatcher = packet_dispatcher or _RecordingPacketDispatcher()
    workflow = PollingWorkflow(
        session_store=store,
        packet_queue=queue,
        packet_dispatcher=dispatcher,
        session_ttl=_SESSION_TTL,
        max_request_body_size=max_request_body_size,
    )
    return workflow, store, queue, dispatcher


def _logs_with_event(logs: list[dict[str, object]], event: str) -> list[dict[str, object]]:
    """captureしたstructured logから指定eventだけを抽出する.

    Args:
        logs (list[dict[str, object]]): structlog captureが返すlog record一覧.
        event (str): 抽出するevent名.

    Returns:
        list[dict[str, object]]: event fieldが一致するlog recordの一覧.
    """
    return [log for log in logs if log.get("event") == event]


class TestPollingWorkflow:
    """PollingWorkflowの認証, dispatch, drain, error recovery順序を検証する."""

    async def test_oversized_body_returns_empty_before_session_lookup(self) -> None:
        """Oversized bodyをsession lookup前に空responseで拒否する契約を検証する.

        Returns:
            None: 空content, 未呼出依存, warning logを検証して完了し, 呼び出し側へ値を返さない.
        """
        workflow, session_store, packet_queue, dispatcher = _make_workflow(max_request_body_size=2)

        with structlog.testing.capture_logs() as logs:
            result = await workflow.execute(PollingWorkflowInput(token=_TOKEN, body=b"abc"))

        assert result.content == b""
        assert session_store.operations == []
        assert dispatcher.calls == []
        assert packet_queue.operations == []
        warning_logs = _logs_with_event(
            cast("list[dict[str, object]]", logs),
            "polling_body_too_large",
        )
        assert len(warning_logs) == 1
        assert warning_logs[0].get("size") == 3
        assert warning_logs[0].get("limit") == 2

    async def test_invalid_token_returns_auth_failed_without_refresh_or_queue_drain(
        self,
    ) -> None:
        """Invalid tokenがrefreshやqueue drainなしでauthentication failureを返す契約を検証する.

        Returns:
            None: login failure packetとsession lookupだけの操作順を確認して完了する.
        """
        workflow, session_store, packet_queue, dispatcher = _make_workflow()

        result = await workflow.execute(PollingWorkflowInput(token="invalid", body=b""))

        assert result.content == login_reply(LoginResult.AUTHENTICATION_FAILED)
        assert session_store.operations == ["session.get:invalid"]
        assert dispatcher.calls == []
        assert packet_queue.operations == []

    async def test_empty_body_refreshes_session_drains_s2c_and_refreshes_queue_ttl(self) -> None:
        """Empty bodyでもsession refresh後にS2Cをdrainしqueue TTLをrefreshする契約を検証する.

        Returns:
            None: response stream, operation順, completion logを確認して完了する.
        """
        workflow, session_store, packet_queue, dispatcher = _make_workflow()
        await session_store.create(_USER_ID, _TOKEN, _session_data())
        await packet_queue.seed(_USER_ID, _QUEUED_A, _QUEUED_B)

        with structlog.testing.capture_logs() as logs:
            result = await workflow.execute(PollingWorkflowInput(token=_TOKEN, body=b""))

        assert result.content == _QUEUED_A + _QUEUED_B
        assert session_store.operations == [
            f"session.get:{_TOKEN}",
            f"session.refresh:{_TOKEN}",
        ]
        assert dispatcher.operations == []
        assert packet_queue.operations == [
            f"queue.refresh:{_USER_ID}:{_SESSION_TTL}",
            f"queue.dequeue:{_USER_ID}",
            f"queue.refresh:{_USER_ID}:{_SESSION_TTL}",
        ]
        complete_logs = _logs_with_event(cast("list[dict[str, object]]", logs), "polling_complete")
        assert len(complete_logs) == 1
        assert complete_logs[0].get("c2s_count") == 0
        assert complete_logs[0].get("s2c_bytes") == len(_QUEUED_A + _QUEUED_B)

    async def test_valid_c2s_packets_are_dispatched_in_order_before_s2c_drain(self) -> None:
        """Valid C2S packetをwire順にdispatchしてからS2Cをdrainする契約を検証する.

        Returns:
            None: dispatch call, session操作, queue操作の順序を確認して完了する.
        """
        workflow, session_store, packet_queue, dispatcher = _make_workflow()
        await session_store.create(_USER_ID, _TOKEN, _session_data())
        await packet_queue.seed(_USER_ID, _QUEUED_A)
        body = b"".join(
            [
                _build_c2s_packet(ClientPacketID.PONG, b"one"),
                _build_c2s_packet(ClientPacketID.EXIT, b"two"),
            ]
        )

        result = await workflow.execute(PollingWorkflowInput(token=_TOKEN, body=body))

        assert result.content == _QUEUED_A
        assert dispatcher.calls == [
            (ClientPacketID.PONG, b"one", _USER_ID),
            (ClientPacketID.EXIT, b"two", _USER_ID),
        ]
        assert session_store.operations == [
            f"session.get:{_TOKEN}",
            f"session.refresh:{_TOKEN}",
        ]
        assert dispatcher.operations == [
            f"dispatch:{ClientPacketID.PONG.name}:6f6e65:{_USER_ID}",
            f"dispatch:{ClientPacketID.EXIT.name}:74776f:{_USER_ID}",
        ]
        assert packet_queue.operations == [
            f"queue.refresh:{_USER_ID}:{_SESSION_TTL}",
            f"queue.dequeue:{_USER_ID}",
            f"queue.refresh:{_USER_ID}:{_SESSION_TTL}",
        ]

    async def test_c2s_parse_error_logs_and_still_drains_s2c(self) -> None:
        """C2S parse errorを記録してもqueued S2Cをdrainする契約を検証する.

        Returns:
            None: response stream, dispatch未実行, parseとcompletion logを確認して完了する.
        """
        workflow, session_store, packet_queue, dispatcher = _make_workflow()
        await session_store.create(_USER_ID, _TOKEN, _session_data())
        await packet_queue.seed(_USER_ID, _QUEUED_A)

        with structlog.testing.capture_logs() as logs:
            result = await workflow.execute(PollingWorkflowInput(token=_TOKEN, body=b"bad"))

        assert result.content == _QUEUED_A
        assert dispatcher.calls == []
        parse_logs = _logs_with_event(cast("list[dict[str, object]]", logs), "c2s_parse_error")
        assert len(parse_logs) == 1
        complete_logs = _logs_with_event(cast("list[dict[str, object]]", logs), "polling_complete")
        assert len(complete_logs) == 1
        assert complete_logs[0].get("c2s_count") == 0

    async def test_handler_error_logs_and_continues_to_remaining_packets(self) -> None:
        """C2S handler errorを記録して後続packetを継続dispatchする契約を検証する.

        Returns:
            None: 両dispatch call, handler error log, completion countを確認して完了する.
        """
        dispatcher = _RecordingPacketDispatcher(failing_packets={ClientPacketID.PONG})
        workflow, session_store, packet_queue, dispatcher = _make_workflow(
            packet_dispatcher=dispatcher
        )
        await session_store.create(_USER_ID, _TOKEN, _session_data())
        await packet_queue.seed(_USER_ID, _QUEUED_B)
        body = b"".join(
            [
                _build_c2s_packet(ClientPacketID.PONG, b"bad"),
                _build_c2s_packet(ClientPacketID.EXIT, b"ok"),
            ]
        )

        with structlog.testing.capture_logs() as logs:
            result = await workflow.execute(PollingWorkflowInput(token=_TOKEN, body=body))

        assert result.content == _QUEUED_B
        assert dispatcher.calls == [
            (ClientPacketID.PONG, b"bad", _USER_ID),
            (ClientPacketID.EXIT, b"ok", _USER_ID),
        ]
        handler_logs = _logs_with_event(cast("list[dict[str, object]]", logs), "c2s_handler_error")
        assert len(handler_logs) == 1
        assert handler_logs[0].get("packet") == ClientPacketID.PONG.name
        assert handler_logs[0].get("payload_size") == 3
        complete_logs = _logs_with_event(cast("list[dict[str, object]]", logs), "polling_complete")
        assert len(complete_logs) == 1
        assert complete_logs[0].get("c2s_count") == 2
