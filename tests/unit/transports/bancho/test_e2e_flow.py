# ruff: noqa: PLR2004
# pyright: reportUnusedFunction=false
"""End-to-end integration test: read_packets → PacketDispatcher.dispatch.

Validates the full C2S packet reception flow described in design.md:
  1. Binary byte stream → read_packets() → list of (ClientPacketID, payload)
  2. For each packet → dispatcher.dispatch() → correct handler called

Requirements coverage:
- Req 4.1: Read C2S packets from byte stream
- Req 4.2: Read multiple concatenated packets
- Req 5.2: Dispatch calls registered handler for matching ClientPacketID
- Req 5.3: Dispatch ignores unregistered ClientPacketID (no error)
"""

import struct as pystruct

from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.reader import read_packets


def _build_packet(packet_id: int, payload: bytes = b"") -> bytes:
    """Build a raw packet: header (7 bytes) + payload."""
    return pystruct.pack("<HBI", packet_id, 0, len(payload)) + payload


class TestReadPacketsToDispatch:
    """End-to-end: byte stream → read_packets → dispatch → handler calls."""

    async def test_single_packet_dispatches_to_correct_handler(self) -> None:
        """A single-packet stream calls only the matching handler."""
        dp = PacketDispatcher()
        called_with: list[tuple[ClientPacketID, bytes]] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(payload: bytes) -> None:
            called_with.append((ClientPacketID.PONG, payload))

        data = _build_packet(ClientPacketID.PONG, b"")
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload)

        assert len(called_with) == 1
        assert called_with[0] == (ClientPacketID.PONG, b"")

    async def test_multiple_packets_dispatch_in_order(self) -> None:
        """Multiple concatenated packets dispatch to their respective handlers in order."""
        dp = PacketDispatcher()
        call_log: list[tuple[ClientPacketID, bytes]] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(payload: bytes) -> None:
            call_log.append((ClientPacketID.PONG, payload))

        @dp.register(ClientPacketID.SEND_MESSAGE)
        async def handle_msg(payload: bytes) -> None:
            call_log.append((ClientPacketID.SEND_MESSAGE, payload))

        @dp.register(ClientPacketID.EXIT)
        async def handle_exit(payload: bytes) -> None:
            call_log.append((ClientPacketID.EXIT, payload))

        msg_payload = b"\xaa\xbb\xcc"
        data = (
            _build_packet(ClientPacketID.PONG, b"")
            + _build_packet(ClientPacketID.SEND_MESSAGE, msg_payload)
            + _build_packet(ClientPacketID.EXIT, b"\x01")
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload)

        assert len(call_log) == 3
        assert call_log[0] == (ClientPacketID.PONG, b"")
        assert call_log[1] == (ClientPacketID.SEND_MESSAGE, msg_payload)
        assert call_log[2] == (ClientPacketID.EXIT, b"\x01")

    async def test_unregistered_packet_id_silently_skipped(self) -> None:
        """Packets with no registered handler are silently skipped during dispatch."""
        dp = PacketDispatcher()
        called_ids: list[ClientPacketID] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(_payload: bytes) -> None:
            called_ids.append(ClientPacketID.PONG)

        # EXIT has no handler registered
        data = (
            _build_packet(ClientPacketID.PONG, b"")
            + _build_packet(ClientPacketID.EXIT, b"")
            + _build_packet(ClientPacketID.PONG, b"")
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload)

        assert called_ids == [ClientPacketID.PONG, ClientPacketID.PONG]

    async def test_handler_receives_correct_payload(self) -> None:
        """Each handler receives exactly the payload bytes from its packet."""
        dp = PacketDispatcher()
        received_payloads: dict[ClientPacketID, list[bytes]] = {
            ClientPacketID.SEND_MESSAGE: [],
            ClientPacketID.STATUS_CHANGE: [],
        }

        @dp.register(ClientPacketID.SEND_MESSAGE)
        async def handle_msg(payload: bytes) -> None:
            received_payloads[ClientPacketID.SEND_MESSAGE].append(payload)

        @dp.register(ClientPacketID.STATUS_CHANGE)
        async def handle_status(payload: bytes) -> None:
            received_payloads[ClientPacketID.STATUS_CHANGE].append(payload)

        payload_a = b"\x01\x02\x03\x04\x05"
        payload_b = b"\xff\xfe"
        data = _build_packet(ClientPacketID.SEND_MESSAGE, payload_a) + _build_packet(
            ClientPacketID.STATUS_CHANGE, payload_b
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload)

        assert received_payloads[ClientPacketID.SEND_MESSAGE] == [payload_a]
        assert received_payloads[ClientPacketID.STATUS_CHANGE] == [payload_b]

    async def test_unknown_packet_ids_filtered_before_dispatch(self) -> None:
        """Unknown packet IDs (not in ClientPacketID) are filtered by read_packets,
        so the dispatcher never sees them."""
        dp = PacketDispatcher()
        dispatched_ids: list[ClientPacketID] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(_payload: bytes) -> None:
            dispatched_ids.append(ClientPacketID.PONG)

        # 999 is not a valid ClientPacketID
        data = (
            _build_packet(999, b"\x00\x00")
            + _build_packet(ClientPacketID.PONG, b"")
            + _build_packet(998, b"")
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload)

        assert dispatched_ids == [ClientPacketID.PONG]

    async def test_empty_stream_dispatches_nothing(self) -> None:
        """An empty byte stream produces no packets and no dispatch calls."""
        dp = PacketDispatcher()
        called = False

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(_payload: bytes) -> None:
            nonlocal called
            called = True

        packets = read_packets(b"")

        for pid, payload in packets:
            await dp.dispatch(pid, payload)

        assert not called
