"""C2S byte stream の read_packets から PacketDispatcher.dispatch までを検証する.

packet stream の parse, wire順 dispatch, handler routing, 未登録 packet の無視を確認する.
"""

import struct as pystruct

from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.reader import read_packets


def _build_packet(packet_id: int, payload: bytes = b"") -> bytes:
    """Test 用 raw Bancho packet を header と payload から構築する.

    Args:
        packet_id (int): uint16 header field に入れる packet ID.
        payload (bytes): header の直後に連結する payload bytes.

    Returns:
        bytes: 7 byte little-endian header と payload を連結した raw packet.
    """
    return pystruct.pack("<HBI", packet_id, 0, len(payload)) + payload


class TestReadPacketsToDispatch:
    """C2S byte stream が parse 後に対応する handler へ dispatch されることを検証する."""

    async def test_single_packet_dispatches_to_correct_handler(self) -> None:
        """単一 packet stream が対応する handler だけを呼び出すことを検証する."""
        dp = PacketDispatcher()
        called_with: list[tuple[ClientPacketID, bytes]] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(payload: bytes, _user_id: int) -> None:
            """PONG packet と受信 payload を call record に追加する."""
            called_with.append((ClientPacketID.PONG, payload))

        _ = handle_pong

        data = _build_packet(ClientPacketID.PONG, b"")
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload, 1)

        assert len(called_with) == 1
        assert called_with[0] == (ClientPacketID.PONG, b"")

    async def test_multiple_packets_dispatch_in_order(self) -> None:
        """連結した複数 packet が wire順に対応する handler へ dispatch されることを検証する."""
        dp = PacketDispatcher()
        call_log: list[tuple[ClientPacketID, bytes]] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(payload: bytes, _user_id: int) -> None:
            """PONG packet と受信 payload を call log に追加する."""
            call_log.append((ClientPacketID.PONG, payload))

        _ = handle_pong

        @dp.register(ClientPacketID.SEND_MESSAGE)
        async def handle_msg(payload: bytes, _user_id: int) -> None:
            """SEND_MESSAGE packet と受信 payload を call log に追加する."""
            call_log.append((ClientPacketID.SEND_MESSAGE, payload))

        _ = handle_msg

        @dp.register(ClientPacketID.EXIT)
        async def handle_exit(payload: bytes, _user_id: int) -> None:
            """EXIT packet と受信 payload を call log に追加する."""
            call_log.append((ClientPacketID.EXIT, payload))

        _ = handle_exit

        msg_payload = b"\xaa\xbb\xcc"
        data = (
            _build_packet(ClientPacketID.PONG, b"")
            + _build_packet(ClientPacketID.SEND_MESSAGE, msg_payload)
            + _build_packet(ClientPacketID.EXIT, b"\x01")
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload, 1)

        assert len(call_log) == 3
        assert call_log[0] == (ClientPacketID.PONG, b"")
        assert call_log[1] == (ClientPacketID.SEND_MESSAGE, msg_payload)
        assert call_log[2] == (ClientPacketID.EXIT, b"\x01")

    async def test_unregistered_packet_id_silently_skipped(self) -> None:
        """未登録 packet ID が dispatch 中に無視されることを検証する."""
        dp = PacketDispatcher()
        called_ids: list[ClientPacketID] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(_payload: bytes, _user_id: int) -> None:
            """PONG dispatch を packet ID list に記録する."""
            called_ids.append(ClientPacketID.PONG)

        _ = handle_pong

        # EXIT has no handler registered
        data = (
            _build_packet(ClientPacketID.PONG, b"")
            + _build_packet(ClientPacketID.EXIT, b"")
            + _build_packet(ClientPacketID.PONG, b"")
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload, 1)

        assert called_ids == [ClientPacketID.PONG, ClientPacketID.PONG]

    async def test_handler_receives_correct_payload(self) -> None:
        """各 handler が対応する packet の original payload bytes を受け取ることを検証する."""
        dp = PacketDispatcher()
        received_payloads: dict[ClientPacketID, list[bytes]] = {
            ClientPacketID.SEND_MESSAGE: [],
            ClientPacketID.STATUS_CHANGE: [],
        }

        @dp.register(ClientPacketID.SEND_MESSAGE)
        async def handle_msg(payload: bytes, _user_id: int) -> None:
            """SEND_MESSAGE payload を packet ID ごとの list に記録する."""
            received_payloads[ClientPacketID.SEND_MESSAGE].append(payload)

        _ = handle_msg

        @dp.register(ClientPacketID.STATUS_CHANGE)
        async def handle_status(payload: bytes, _user_id: int) -> None:
            """STATUS_CHANGE payload を packet ID ごとの list に記録する."""
            received_payloads[ClientPacketID.STATUS_CHANGE].append(payload)

        _ = handle_status

        payload_a = b"\x01\x02\x03\x04\x05"
        payload_b = b"\xff\xfe"
        data = _build_packet(ClientPacketID.SEND_MESSAGE, payload_a) + _build_packet(
            ClientPacketID.STATUS_CHANGE, payload_b
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload, 1)

        assert received_payloads[ClientPacketID.SEND_MESSAGE] == [payload_a]
        assert received_payloads[ClientPacketID.STATUS_CHANGE] == [payload_b]

    async def test_unknown_packet_ids_filtered_before_dispatch(self) -> None:
        """未知 packet ID が read_packets により dispatch 前に除外されることを検証する."""
        dp = PacketDispatcher()
        dispatched_ids: list[ClientPacketID] = []

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(_payload: bytes, _user_id: int) -> None:
            """PONG dispatch を packet ID list に記録する."""
            dispatched_ids.append(ClientPacketID.PONG)

        _ = handle_pong

        # 999 is not a valid ClientPacketID
        data = (
            _build_packet(999, b"\x00\x00")
            + _build_packet(ClientPacketID.PONG, b"")
            + _build_packet(998, b"")
        )
        packets = read_packets(data)

        for pid, payload in packets:
            await dp.dispatch(pid, payload, 1)

        assert dispatched_ids == [ClientPacketID.PONG]

    async def test_empty_stream_dispatches_nothing(self) -> None:
        """空 byte stream が packet も handler dispatch も発生させないことを検証する."""
        dp = PacketDispatcher()
        called = False

        @dp.register(ClientPacketID.PONG)
        async def handle_pong(_payload: bytes, _user_id: int) -> None:
            """PONG handler が呼び出されたことを boolean flag に記録する."""
            nonlocal called
            called = True

        _ = handle_pong

        packets = read_packets(b"")

        for pid, payload in packets:
            await dp.dispatch(pid, payload, 1)

        assert not called
