"""Bancho protocol error hierarchy と transport package import contract を検証する.

PacketError の subclass, error message, catch behavior, public package import を確認する.
"""

from __future__ import annotations

import caterpillar
import pytest
from caterpillar.py import boolean, struct, uint16, uint32

import osu_server.transports.stable.bancho.handlers
import osu_server.transports.stable.bancho.protocol
import osu_server.transports.stable.bancho.protocol.c2s
import osu_server.transports.stable.bancho.protocol.s2c
from osu_server.transports.stable.bancho.protocol import (
    DuplicateHandlerError,
    PacketError,
    PacketReadError,
)


class TestCaterpillarImport:
    """Bancho protocol が依存する caterpillar-py API を import できることを検証する."""

    def test_caterpillar_core_importable(self) -> None:
        """Caterpillar top-level module を import できることを検証する."""
        assert caterpillar is not None

    def test_caterpillar_struct_importable(self) -> None:
        """Caterpillar struct decorator を import できることを検証する."""
        assert struct is not None

    def test_caterpillar_fields_importable(self) -> None:
        """Bancho header に使う caterpillar field definition を import できることを検証する."""
        assert uint16 is not None
        assert uint32 is not None
        assert boolean is not None


class TestErrorHierarchy:
    """Bancho protocol exception hierarchy の inheritance と message behavior を検証する."""

    def test_packet_error_is_exception(self) -> None:
        """PacketError が built-in Exception の subclass であることを検証する."""
        assert issubclass(PacketError, Exception)

    def test_packet_read_error_is_packet_error(self) -> None:
        """PacketReadError が PacketError の subclass であることを検証する."""
        assert issubclass(PacketReadError, PacketError)

    def test_duplicate_handler_error_is_packet_error(self) -> None:
        """DuplicateHandlerError が PacketError の subclass であることを検証する."""
        assert issubclass(DuplicateHandlerError, PacketError)

    def test_packet_error_instantiation_with_message(self) -> None:
        """PacketError が constructor message を保持することを検証する."""
        err = PacketError("test error")
        assert str(err) == "test error"

    def test_packet_read_error_instantiation_with_message(self) -> None:
        """PacketReadError が constructor message を保持することを検証する."""
        err = PacketReadError("insufficient header bytes")
        assert str(err) == "insufficient header bytes"

    def test_duplicate_handler_error_instantiation_with_message(self) -> None:
        """DuplicateHandlerError が constructor message を保持することを検証する."""
        err = DuplicateHandlerError("handler already registered")
        assert str(err) == "handler already registered"

    def test_packet_read_error_catchable_as_packet_error(self) -> None:
        """PacketReadError を共通の PacketError として catch できることを検証する."""
        with pytest.raises(PacketError):
            raise PacketReadError("data too short")

    def test_duplicate_handler_error_catchable_as_packet_error(self) -> None:
        """DuplicateHandlerError を共通の PacketError として catch できることを検証する."""
        with pytest.raises(PacketError):
            raise DuplicateHandlerError("duplicate")


class TestPackageStructure:
    """Bancho transport package と protocol public import contract を検証する."""

    def test_bancho_protocol_package_importable(self) -> None:
        """bancho.protocol package を import できることを検証する."""
        assert osu_server.transports.stable.bancho.protocol is not None

    def test_bancho_protocol_c2s_package_importable(self) -> None:
        """bancho.protocol.c2s package を import できることを検証する."""
        assert osu_server.transports.stable.bancho.protocol.c2s is not None

    def test_bancho_protocol_s2c_package_importable(self) -> None:
        """bancho.protocol.s2c package を import できることを検証する."""
        assert osu_server.transports.stable.bancho.protocol.s2c is not None

    def test_bancho_handlers_package_importable(self) -> None:
        """bancho.handlers package を import できることを検証する."""
        assert osu_server.transports.stable.bancho.handlers is not None

    def test_error_classes_importable_from_protocol_init(self) -> None:
        """Protocol package が全 error class を public API として再公開することを検証する."""
        assert PacketError is not None
        assert PacketReadError is not None
        assert DuplicateHandlerError is not None
