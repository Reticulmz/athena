"""Tests for Starlette-independent polling workflow pipeline."""

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
    """Session store that records polling call order."""

    operations: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.operations = []

    @override
    async def get(self, token: str) -> SessionData | None:
        self.operations.append(f"session.get:{token}")
        return await super().get(token)

    @override
    async def refresh(self, token: str) -> bool:
        self.operations.append(f"session.refresh:{token}")
        return await super().refresh(token)


@final
class _RecordingPacketQueue(InMemoryPacketQueue):
    """Packet queue that records drain and TTL refresh order."""

    operations: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.operations = []

    async def seed(self, user_id: int, *data: bytes) -> None:
        await super().refresh_ttl(user_id, _SESSION_TTL)
        await super().enqueue(user_id, *data)
        self.operations.clear()

    @override
    async def dequeue_all(self, user_id: int) -> bytes:
        self.operations.append(f"queue.dequeue:{user_id}")
        return await super().dequeue_all(user_id)

    @override
    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        self.operations.append(f"queue.refresh:{user_id}:{ttl}")
        await super().refresh_ttl(user_id, ttl)


@final
class _RecordingPacketDispatcher(PacketDispatcher):
    """Packet dispatcher that records C2S dispatch calls."""

    operations: list[str]
    calls: list[tuple[ClientPacketID, bytes, int]]
    failing_packets: set[ClientPacketID]

    def __init__(self, *, failing_packets: set[ClientPacketID] | None = None) -> None:
        super().__init__()
        self.operations = []
        self.calls = []
        self.failing_packets = failing_packets or set()

    @override
    async def dispatch(self, packet_id: ClientPacketID, payload: bytes, user_id: int) -> None:
        self.operations.append(f"dispatch:{packet_id.name}:{payload.hex()}:{user_id}")
        self.calls.append((packet_id, payload, user_id))
        if packet_id in self.failing_packets:
            msg = f"intentional failure for {packet_id.name}"
            raise RuntimeError(msg)


def _session_data(user_id: int = _USER_ID) -> SessionData:
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
    return [log for log in logs if log.get("event") == event]


class TestPollingWorkflow:
    async def test_oversized_body_returns_empty_before_session_lookup(self) -> None:
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
        workflow, session_store, packet_queue, dispatcher = _make_workflow()

        result = await workflow.execute(PollingWorkflowInput(token="invalid", body=b""))

        assert result.content == login_reply(LoginResult.AUTHENTICATION_FAILED)
        assert session_store.operations == ["session.get:invalid"]
        assert dispatcher.calls == []
        assert packet_queue.operations == []

    async def test_empty_body_refreshes_session_drains_s2c_and_refreshes_queue_ttl(self) -> None:
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
