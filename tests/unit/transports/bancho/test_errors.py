"""Tests for bancho protocol error hierarchy (Task 1.1).

Validates:
- Requirements 4.4, 4.5: PacketReadError for data-insufficient scenarios
- Requirement 5.5: DuplicateHandlerError for duplicate handler registration
- Design: Error Handling section — PacketError base, PacketReadError, DuplicateHandlerError
"""

from __future__ import annotations

import caterpillar
import pytest
from caterpillar.py import boolean, struct, uint16, uint32

import osu_server.transports.bancho.handlers
import osu_server.transports.bancho.protocol
import osu_server.transports.bancho.protocol.c2s
import osu_server.transports.bancho.protocol.s2c
from osu_server.transports.bancho.protocol import (
    DuplicateHandlerError,
    PacketError,
    PacketReadError,
)


class TestCaterpillarImport:
    """Verify caterpillar-py dependency is installed and importable."""

    def test_caterpillar_core_importable(self) -> None:
        assert caterpillar is not None

    def test_caterpillar_struct_importable(self) -> None:
        assert struct is not None

    def test_caterpillar_fields_importable(self) -> None:
        assert uint16 is not None
        assert uint32 is not None
        assert boolean is not None


class TestErrorHierarchy:
    """Verify protocol exception hierarchy matches design spec."""

    def test_packet_error_is_exception(self) -> None:
        assert issubclass(PacketError, Exception)

    def test_packet_read_error_is_packet_error(self) -> None:
        assert issubclass(PacketReadError, PacketError)

    def test_duplicate_handler_error_is_packet_error(self) -> None:
        assert issubclass(DuplicateHandlerError, PacketError)

    def test_packet_error_instantiation_with_message(self) -> None:
        err = PacketError("test error")
        assert str(err) == "test error"

    def test_packet_read_error_instantiation_with_message(self) -> None:
        err = PacketReadError("insufficient header bytes")
        assert str(err) == "insufficient header bytes"

    def test_duplicate_handler_error_instantiation_with_message(self) -> None:
        err = DuplicateHandlerError("handler already registered")
        assert str(err) == "handler already registered"

    def test_packet_read_error_catchable_as_packet_error(self) -> None:
        with pytest.raises(PacketError):
            raise PacketReadError("data too short")

    def test_duplicate_handler_error_catchable_as_packet_error(self) -> None:
        with pytest.raises(PacketError):
            raise DuplicateHandlerError("duplicate")


class TestPackageStructure:
    """Verify the bancho transport package structure is importable."""

    def test_bancho_protocol_package_importable(self) -> None:
        assert osu_server.transports.bancho.protocol is not None

    def test_bancho_protocol_c2s_package_importable(self) -> None:
        assert osu_server.transports.bancho.protocol.c2s is not None

    def test_bancho_protocol_s2c_package_importable(self) -> None:
        assert osu_server.transports.bancho.protocol.s2c is not None

    def test_bancho_handlers_package_importable(self) -> None:
        assert osu_server.transports.bancho.handlers is not None

    def test_error_classes_importable_from_protocol_init(self) -> None:
        assert PacketError is not None
        assert PacketReadError is not None
        assert DuplicateHandlerError is not None
