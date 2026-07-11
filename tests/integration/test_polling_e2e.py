"""E2E polling pipeline + edge case tests (Tasks 6.1, 6.2).

Tests the full login -> poll -> C2S dispatch -> S2C drain flow through
the refactored BanchoEndpoint + DI container.

Uses InMemoryPacketQueue for deterministic tests; Redis-specific
concurrent safety is tested in test_redis_packet_queue.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import struct
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final

from osu_server.domain.beatmaps import BeatmapFileSource, BeatmapMode

if TYPE_CHECKING:
    from glide_shared.constants import TEncodable
    from starlette.applications import Starlette
    from structlog.typing import EventDict

import structlog.testing
from caterpillar.model import pack
from starlette.testclient import TestClient
from taskiq import AsyncBroker, InMemoryBroker

from osu_server.app import create_app
from osu_server.composition.providers.test import (
    TestProviderSet,
    make_in_memory_runtime_provider_set,
    replace_value,
)
from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authentication import LoginResult, RegistrationForm
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.beatmaps import FetchBeatmapFileUseCase
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID, ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate
from tests.support.app import resolve_dependency
from tests.support.persistence import (
    attach_beatmap_file,
    seed_beatmap_fetch_state,
    seed_beatmapset,
    seed_role,
)
from tests.support.service_availability import require_tcp_service_url

# -- Constants -----------------------------------------------------------

_PASSWORD = "SecurePass1234"
_PASSWORD_MD5 = hashlib.md5(_PASSWORD.encode()).hexdigest()
_ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED,
    position=0,
)
_OK = HTTPStatus.OK
_HEADER_SIZE = 7
_BANCHO_URL = "http://c.athena.localhost/"
_STATUS_BEATMAP_ID = 75
_STATUS_BEATMAPSET_ID = 1
_STATUS_CHECKSUM = "0123456789abcdef0123456789abcdef"
_STATUS_FILENAME = "Camellia - Exit This Earth's Atomosphere (Realazy) [Insane].osu"
_MODE_SWITCH_PACKET_BODY = bytes.fromhex(
    "0000000e000000000b000b0000000000016bb92000",
)
_MODE_SWITCH_BEATMAP_ID = 2_144_619
_STATUS_CHANGE_RESPONSE_PACKET_IDS = [
    ServerPacketID.USER_STATS,
]

# Module-level env defaults for test DI container
_ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
_ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")


# -- Helpers --------------------------------------------------------------


def _build_login_body() -> bytes:
    client_info = "20231111|9|1|hash1:hash2:hash3|0"
    return f"TestUser\n{_PASSWORD_MD5}\n{client_info}\n".encode()


def _build_c2s_packet(packet_id: ClientPacketID, payload: bytes = b"") -> bytes:
    return struct.pack("<HBI", packet_id.value, 0, len(payload)) + payload


def _server_packet_ids(packet_stream: bytes) -> list[ServerPacketID]:
    packet_ids: list[ServerPacketID] = []
    offset = 0
    while offset < len(packet_stream):
        unpacked = struct.unpack(
            "<HBI",
            packet_stream[offset : offset + _HEADER_SIZE],
        )
        packet_id = cast("int", unpacked[0])
        payload_size = cast("int", unpacked[2])
        packet_ids.append(ServerPacketID(packet_id))
        offset += _HEADER_SIZE + payload_size
    return packet_ids


def _status_payload(
    *,
    beatmap_id: int,
    beatmap_md5: str = _STATUS_CHECKSUM,
) -> bytes:
    return pack(
        StatusUpdate(
            status=2,
            status_text="playing",
            beatmap_md5=beatmap_md5,
            mods=0,
            play_mode=0,
            beatmap_id=beatmap_id,
        )
    )


def _extract_login_reply(body: bytes) -> int:
    unpacked = struct.unpack("<i", body[_HEADER_SIZE : _HEADER_SIZE + 4])
    return cast("int", unpacked[0])


def _make_test_app(
    *,
    max_request_body_size: int = 1_048_576,
    packet_queue_max_size: int = 4096,
    broker: AsyncBroker | None = None,
    packet_dispatcher: PacketDispatcher | None = None,
) -> Starlette:
    """Create the Starlette app with full DI container and BanchoEndpoint."""
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    os.environ["MAX_REQUEST_BODY_SIZE"] = str(max_request_body_size)
    os.environ["PACKET_QUEUE_MAX_SIZE"] = str(packet_queue_max_size)
    overrides: list[TestProviderSet] = [
        make_in_memory_runtime_provider_set(
            packet_queue_max_size=packet_queue_max_size,
        )
    ]
    if broker is not None:
        overrides.append(TestProviderSet(replace_value(AsyncBroker, broker)))
    if packet_dispatcher is not None:
        overrides.append(TestProviderSet(replace_value(PacketDispatcher, packet_dispatcher)))
    return create_app(provider_overrides=tuple(overrides))


async def _seed_default_role(app: Starlette) -> None:
    """Seed the Default role into command-side in-memory persistence."""
    await seed_role(app, _ROLE_DEFAULT)


async def _seed_status_change_beatmap(app: Starlette) -> None:
    """Seed a known beatmap with fresh metadata and missing osu file."""
    now = datetime.now(UTC)
    next_refresh = now + timedelta(days=30)
    beatmap = Beatmap(
        id=_STATUS_BEATMAP_ID,
        beatmapset_id=_STATUS_BEATMAPSET_ID,
        checksum_md5=_STATUS_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Insane",
        total_length=240,
        hit_length=220,
        max_combo=1234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=now,
        next_refresh_at=next_refresh,
    )
    await seed_beatmapset(
        app,
        BeatmapSet(
            id=_STATUS_BEATMAPSET_ID,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            artist_unicode=None,
            title_unicode=None,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(beatmap,),
            last_fetched_at=now,
            next_refresh_at=next_refresh,
        ),
    )


async def _attach_status_change_beatmap_file(app: Starlette) -> None:
    now = datetime.now(UTC)
    _ = await attach_beatmap_file(
        app,
        BeatmapFileAttachment(
            beatmap_id=_STATUS_BEATMAP_ID,
            blob_id=1,
            checksum_md5=_STATUS_CHECKSUM,
            source=BeatmapFileSource.LEGACY_OFFICIAL,
            original_filename=_STATUS_FILENAME,
            fetched_at=now,
            verified_at=now,
        ),
    )


def _events_with(logs: list[EventDict], event_name: str) -> list[EventDict]:
    return [entry for entry in logs if entry.get("event") == event_name]


async def _resolve_services(
    app: Starlette,
) -> tuple[PacketDispatcher, PacketQueue, SessionStore, AuthService]:
    """Resolve test-facing services from the container after lifespan."""
    await _seed_default_role(app)
    return (
        await resolve_dependency(app, PacketDispatcher),
        await resolve_dependency(app, PacketQueue),
        await resolve_dependency(app, SessionStore),
        await resolve_dependency(app, AuthService),
    )


async def _login_and_get_token(
    auth_service: AuthService,
    client: TestClient,
) -> str:
    _ = await auth_service.register(
        RegistrationForm(username="TestUser", email="t@e.com", password=_PASSWORD),
    )
    resp = client.post(_BANCHO_URL, content=_build_login_body())
    assert resp.status_code == _OK
    return resp.headers["cho-token"]


@final
class RecordingBeatmapFetchQueue:
    """In-memory taskiq target recorder for beatmap fetch enqueue assertions."""

    broker: AsyncBroker
    enqueued_targets: list[BeatmapFetchTarget]
    file_fetch_use_case: FetchBeatmapFileUseCase | None

    def __init__(self) -> None:
        self.broker = InMemoryBroker(await_inplace=True)
        self.enqueued_targets = []
        self.file_fetch_use_case = None

        @self.broker.task(task_name="fetch_beatmap_file")
        async def fetch_beatmap_file(target_type: str, target_key: str) -> None:
            target = BeatmapFetchTarget.from_queue_payload(
                target_type=target_type,
                target_key=target_key,
            )
            self.enqueued_targets.append(target)
            if self.file_fetch_use_case is not None:
                await self.file_fetch_use_case.execute(target)

        @self.broker.task(task_name="fetch_beatmap_metadata")
        async def fetch_beatmap_metadata(target_type: str, target_key: str) -> None:
            self.enqueued_targets.append(
                BeatmapFetchTarget.from_queue_payload(
                    target_type=target_type,
                    target_key=target_key,
                )
            )

        _ = (fetch_beatmap_file, fetch_beatmap_metadata)


# ═══════════════════════════════════════════════════════════════════════
# Task 6.1: E2E Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════


class TestPollingE2EFlow:
    """Login -> poll -> C2S -> S2C complete flow (Req 1.1, 2.1, 2.4)."""

    async def test_full_c2s_to_s2c_flow(self) -> None:
        """C2S handler enqueue on first poll appears in the same response."""
        app = _make_test_app(packet_dispatcher=PacketDispatcher())
        user_id_ref: list[int] = []

        with TestClient(app, raise_server_exceptions=False) as client:
            dispatcher, packet_queue, session_store, auth_service = await _resolve_services(app)

            @dispatcher.register(ClientPacketID.SEND_MESSAGE)
            async def handler(_payload: bytes, *_a: object, **_kw: object) -> None:
                await packet_queue.enqueue(user_id_ref[0], b"\xca\xfe")

            _ = handler

            token = await _login_and_get_token(auth_service, client)

            session = await session_store.get(token)
            assert session is not None
            user_id_ref.append(session.user_id)

            # Second poll with C2S packet
            body = _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\x01")
            resp = client.post(_BANCHO_URL, headers={"osu-token": token}, content=body)
            assert resp.content == b"\xca\xfe"


class TestStatusChangeWarmupE2E:
    """STATUS_CHANGE triggers warmup through the full polling DI graph."""

    async def test_status_change_by_id_requests_file_fetch_and_keeps_other_packets(self) -> None:
        fetch_queue = RecordingBeatmapFetchQueue()
        app = _make_test_app(broker=fetch_queue.broker)

        with TestClient(app, raise_server_exceptions=False) as client:
            _, packet_queue, session_store, auth_service = await _resolve_services(app)
            await _seed_status_change_beatmap(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            await packet_queue.enqueue(session.user_id, b"\xca\xfe")

            body = _build_c2s_packet(
                ClientPacketID.STATUS_CHANGE,
                _status_payload(beatmap_id=_STATUS_BEATMAP_ID),
            ) + _build_c2s_packet(ClientPacketID.PONG)
            with structlog.testing.capture_logs() as logs:
                resp = client.post(_BANCHO_URL, headers={"osu-token": token}, content=body)

        assert resp.content.startswith(b"\xca\xfe")
        assert _server_packet_ids(resp.content[2:]) == _STATUS_CHANGE_RESPONSE_PACKET_IDS
        assert resp.content[2:].startswith(
            user_stats(
                user_id=session.user_id,
                status=2,
                status_text="playing",
                beatmap_md5=_STATUS_CHECKSUM,
                mods=0,
                play_mode=0,
                beatmap_id=_STATUS_BEATMAP_ID,
                ranked_score=0,
                accuracy=0.0,
                play_count=0,
                total_score=0,
                rank=0,
                pp=0,
            )
        )
        file_target = BeatmapFetchTarget.file_by_beatmap_id(_STATUS_BEATMAP_ID)
        assert fetch_queue.enqueued_targets == [file_target]

        warmup_events = _events_with(logs, "beatmap_file_warmup")
        assert len(warmup_events) == 1
        warmup = warmup_events[0]
        assert warmup.get("entrance") == "stable_status_change"
        assert warmup.get("outcome") == "requested"
        assert warmup.get("beatmap_id") == _STATUS_BEATMAP_ID
        assert warmup.get("checksum_md5") is None
        assert warmup.get("reason") == "osu_file_required_but_unavailable"
        assert any(
            entry.get("event") == "c2s_packet" and entry.get("packet") == "PONG" for entry in logs
        )

    async def test_status_change_accepts_stable_present_empty_strings_and_returns_stats(
        self,
    ) -> None:
        fetch_queue = RecordingBeatmapFetchQueue()
        app = _make_test_app(broker=fetch_queue.broker)

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None

            with structlog.testing.capture_logs() as logs:
                resp = client.post(
                    _BANCHO_URL,
                    headers={"osu-token": token},
                    content=_MODE_SWITCH_PACKET_BODY,
                )

        assert _server_packet_ids(resp.content) == _STATUS_CHANGE_RESPONSE_PACKET_IDS
        assert resp.content.startswith(
            user_stats(
                user_id=session.user_id,
                status=0,
                status_text="",
                beatmap_md5="",
                mods=0,
                play_mode=1,
                beatmap_id=_MODE_SWITCH_BEATMAP_ID,
                ranked_score=0,
                accuracy=0.0,
                play_count=0,
                total_score=0,
                rank=0,
                pp=0,
            )
        )
        assert not _events_with(logs, "status_change_warmup_decode_failed")
        assert any(
            entry.get("event") == "c2s_packet" and entry.get("packet") == "STATUS_CHANGE"
            for entry in logs
        )

    async def test_status_change_checksum_fallback_requests_known_file_fetch(self) -> None:
        fetch_queue = RecordingBeatmapFetchQueue()
        app = _make_test_app(broker=fetch_queue.broker)

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, _, auth_service = await _resolve_services(app)
            await _seed_status_change_beatmap(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})

            body = _build_c2s_packet(
                ClientPacketID.STATUS_CHANGE,
                _status_payload(beatmap_id=0, beatmap_md5=_STATUS_CHECKSUM.upper()),
            )
            with structlog.testing.capture_logs() as logs:
                resp = client.post(_BANCHO_URL, headers={"osu-token": token}, content=body)

        assert _server_packet_ids(resp.content) == _STATUS_CHANGE_RESPONSE_PACKET_IDS
        file_target = BeatmapFetchTarget.file_by_beatmap_id(_STATUS_BEATMAP_ID)
        assert fetch_queue.enqueued_targets == [file_target]

        warmup_events = _events_with(logs, "beatmap_file_warmup")
        assert len(warmup_events) == 1
        warmup = warmup_events[0]
        assert warmup.get("entrance") == "stable_status_change"
        assert warmup.get("outcome") == "requested"
        assert warmup.get("beatmap_id") is None
        assert warmup.get("checksum_md5") == _STATUS_CHECKSUM
        assert warmup.get("reason") == "osu_file_required_but_unavailable"

    async def test_repeated_status_change_converges_to_one_pending_fetch(self) -> None:
        fetch_queue = RecordingBeatmapFetchQueue()
        app = _make_test_app(broker=fetch_queue.broker)

        with TestClient(app, raise_server_exceptions=False) as client:
            query_repository = await resolve_dependency(app, BeatmapQueryRepository)
            fetch_queue.file_fetch_use_case = await resolve_dependency(
                app, FetchBeatmapFileUseCase
            )
            _, _, _, auth_service = await _resolve_services(app)
            await _seed_status_change_beatmap(app)
            file_target = BeatmapFetchTarget.file_by_beatmap_id(_STATUS_BEATMAP_ID)
            await seed_beatmap_fetch_state(
                app,
                file_target,
                BeatmapFetchState.PENDING_FETCH,
                datetime.now(UTC),
            )
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})

            packet = _build_c2s_packet(
                ClientPacketID.STATUS_CHANGE,
                _status_payload(beatmap_id=_STATUS_BEATMAP_ID),
            )
            with structlog.testing.capture_logs() as logs:
                resp = client.post(
                    _BANCHO_URL,
                    headers={"osu-token": token},
                    content=packet + packet,
                )

            fetch_record = await query_repository.get_fetch_state(file_target)

        assert _server_packet_ids(resp.content) == _STATUS_CHANGE_RESPONSE_PACKET_IDS * 2
        assert fetch_queue.enqueued_targets == [file_target, file_target]
        assert fetch_record is not None
        assert fetch_record.status is BeatmapFetchState.PENDING_FETCH
        assert fetch_record.attempt_count == 1

        warmup_events = _events_with(logs, "beatmap_file_warmup")
        assert [entry.get("outcome") for entry in warmup_events] == [
            "requested",
            "requested",
        ]
        assert {entry.get("beatmap_id") for entry in warmup_events} == {
            _STATUS_BEATMAP_ID,
        }
        assert {entry.get("checksum_md5") for entry in warmup_events} == {None}

    async def test_status_change_available_file_logs_noop_without_fetch(self) -> None:
        fetch_queue = RecordingBeatmapFetchQueue()
        app = _make_test_app(broker=fetch_queue.broker)

        with TestClient(app, raise_server_exceptions=False) as client:
            query_repository = await resolve_dependency(app, BeatmapQueryRepository)
            _, _, _, auth_service = await _resolve_services(app)
            await _seed_status_change_beatmap(app)
            await _attach_status_change_beatmap_file(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})

            body = _build_c2s_packet(
                ClientPacketID.STATUS_CHANGE,
                _status_payload(beatmap_id=_STATUS_BEATMAP_ID),
            )
            with structlog.testing.capture_logs() as logs:
                resp = client.post(_BANCHO_URL, headers={"osu-token": token}, content=body)

            attachment = await query_repository.get_current_file_attachment(_STATUS_BEATMAP_ID)

        assert _server_packet_ids(resp.content) == _STATUS_CHANGE_RESPONSE_PACKET_IDS
        assert attachment is not None
        assert fetch_queue.enqueued_targets == []

        warmup_events = _events_with(logs, "beatmap_file_warmup")
        assert len(warmup_events) == 1
        warmup = warmup_events[0]
        assert warmup.get("entrance") == "stable_status_change"
        assert warmup.get("outcome") == "already_available"
        assert warmup.get("beatmap_id") == _STATUS_BEATMAP_ID
        assert warmup.get("checksum_md5") is None
        assert warmup.get("reason") == "file_available"


class TestSessionTTLRefresh:
    """Polling refreshes session TTL (Req 5.1)."""

    async def test_session_exists_after_poll(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})
            assert await session_store.exists(token) is True


class TestInvalidTokenRejection:
    """Invalid token returns AUTH_FAILED (Req 6.1)."""

    async def test_invalid_token_returns_auth_failed(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _ = await _resolve_services(app)
            resp = client.post(_BANCHO_URL, headers={"osu-token": "bogus"})
            value = _extract_login_reply(resp.content)
            assert value == LoginResult.AUTHENTICATION_FAILED


class TestNoTokenFallsBackToLogin:
    """No osu-token header -> login flow (Req 6.2 regression)."""

    async def test_no_token_triggers_login(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, _, auth_service = await _resolve_services(app)
            _ = await auth_service.register(
                RegistrationForm(
                    username="TestUser",
                    email="t@e.com",
                    password=_PASSWORD,
                ),
            )
            resp = client.post(_BANCHO_URL, content=_build_login_body())
            assert "cho-token" in resp.headers
            assert _extract_login_reply(resp.content) > 0


class TestBodySizeLimitE2E:
    """Oversized body skips processing (Req 3.4)."""

    async def test_oversized_body_returns_empty(self) -> None:
        app = _make_test_app(max_request_body_size=10)

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, _, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            resp = client.post(
                _BANCHO_URL,
                headers={"osu-token": token},
                content=b"\x00" * 20,
            )
            assert resp.content == b""


# ═══════════════════════════════════════════════════════════════════════
# Task 6.2: Edge Cases and Concurrent Safety
# ═══════════════════════════════════════════════════════════════════════


class TestCorruptPacketEdgeCase:
    """Corrupt C2S header -> parse aborted, S2C drain still works (Req 3.1)."""

    async def test_corrupt_header_still_returns_s2c(self) -> None:
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _, packet_queue, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id = session.user_id
            await packet_queue.enqueue(user_id, b"\xab")

            resp = client.post(
                _BANCHO_URL,
                headers={"osu-token": token},
                content=b"\xff\xff",  # corrupt header
            )
            assert resp.content == b"\xab"


class TestHandlerExceptionEdgeCase:
    """Handler exception -> log + continue subsequent packets (Req 3.2)."""

    async def test_failing_handler_does_not_block_next(self) -> None:
        app = _make_test_app(packet_dispatcher=PacketDispatcher())
        results: list[str] = []

        with TestClient(app, raise_server_exceptions=False) as client:
            dispatcher, _, _, auth_service = await _resolve_services(app)

            @dispatcher.register(ClientPacketID.JOIN_CHANNEL)
            async def failing(_payload: bytes, *_a: object, **_kw: object) -> None:
                msg = "boom"
                raise RuntimeError(msg)

            @dispatcher.register(ClientPacketID.SEND_MESSAGE)
            async def ok(_payload: bytes, *_a: object, **_kw: object) -> None:
                results.append("ok")

            _ = (failing, ok)

            token = await _login_and_get_token(auth_service, client)
            body = _build_c2s_packet(
                ClientPacketID.JOIN_CHANNEL,
                b"\x00",
            ) + _build_c2s_packet(ClientPacketID.SEND_MESSAGE, b"\x00")
            _ = client.post(_BANCHO_URL, headers={"osu-token": token}, content=body)

        assert results == ["ok"]


class TestQueueSizeLimit:
    """Queue over max_size trims oldest packets (Req 4.2)."""

    async def test_oldest_trimmed_when_over_limit(self) -> None:
        app = _make_test_app(packet_queue_max_size=3)

        with TestClient(app, raise_server_exceptions=False) as client:
            _, packet_queue, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})

            session = await session_store.get(token)
            assert session is not None
            user_id = session.user_id

            for i in range(5):
                await packet_queue.enqueue(user_id, bytes([i]))

            resp = client.post(_BANCHO_URL, headers={"osu-token": token})
            assert resp.content == b"\x02\x03\x04"


class TestConcurrentDrainRedis:
    """Concurrent drain with Redis — no duplicate delivery (Req 1.3)."""

    async def test_concurrent_drain_no_duplicates(self) -> None:
        from osu_server.infrastructure.cache.valkey_client import (
            create_valkey_client,
        )
        from osu_server.infrastructure.state.valkey.packet_queue import (
            ValkeyPacketQueue,
        )

        prefix = "athena_e2e_test:"
        valkey_url = require_tcp_service_url("VALKEY_URL", default_port=6379)
        valkey = await create_valkey_client(valkey_url)
        try:
            queue = ValkeyPacketQueue(
                valkey,
                max_size=4096,
                ttl=300,
                key_prefix=prefix,
            )
            await queue.refresh_ttl(user_id=1, ttl=300)

            packet_count = 100
            for i in range(packet_count):
                await queue.enqueue(1, bytes([i % 256]))

            results = await asyncio.gather(
                queue.dequeue_all(user_id=1),
                queue.dequeue_all(user_id=1),
                queue.dequeue_all(user_id=1),
            )

            non_empty = [r for r in results if r != b""]
            assert len(non_empty) == 1
            assert len(non_empty[0]) == packet_count
        finally:
            for pattern in (f"{prefix}packet_queue:*", f"{prefix}pq_meta:*"):
                cursor: str = "0"
                while True:
                    next_cursor, keys = await valkey.scan(
                        cursor,
                        match=pattern,
                        count=100,
                    )
                    if keys:
                        _ = await valkey.delete(cast("list[TEncodable]", keys))
                    cursor = (
                        next_cursor.decode()
                        if isinstance(next_cursor, bytes)
                        else str(next_cursor)
                    )
                    if cursor == "0":
                        break
            await valkey.close()
