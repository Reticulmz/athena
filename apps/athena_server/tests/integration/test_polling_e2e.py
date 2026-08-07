"""Bancho polling pipeline と edge case の integration contract を検証する test.

InMemory DI graph を使い, login, C2S dispatch, S2C drain, beatmap file warmup の
end-to-end behavior を確認する.
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
    """既定の test user 用 stable login request body を組み立てる.

    Returns:
        bytes: username, password MD5, client info を改行区切りにした request body.
    """
    client_info = "20231111|9|1|hash1:hash2:hash3|0"
    return f"TestUser\n{_PASSWORD_MD5}\n{client_info}\n".encode()


def _build_c2s_packet(packet_id: ClientPacketID, payload: bytes = b"") -> bytes:
    """C2S packet header と payload を連結する.

    Args:
        packet_id (ClientPacketID): 送信する client packet の識別子.
        payload (bytes): header の後に配置する packet payload.

    Returns:
        bytes: little-endian header と payload を連結した Bancho packet.
    """
    return struct.pack("<HBI", packet_id.value, 0, len(payload)) + payload


def _server_packet_ids(packet_stream: bytes) -> list[ServerPacketID]:
    """S2C packet stream に含まれる packet ID を順番に取り出す.

    Args:
        packet_stream (bytes): 完全な Bancho server packet stream.

    Returns:
        list[ServerPacketID]: stream 内の packet ID を出現順に並べた値.
    """
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
    """Stable `STATUS_CHANGE` packet 用の status payload を組み立てる.

    Args:
        beatmap_id (int): status に設定する beatmap ID.
        beatmap_md5 (str): status に設定する beatmap checksum MD5.

    Returns:
        bytes: Caterpillar で encode した `StatusUpdate` payload.
    """
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
    """Login response の先頭 packet から signed user ID を取り出す.

    Args:
        body (bytes): `LOGIN_REPLY` payload を先頭に持つ Bancho response body.

    Returns:
        int: response の `LOGIN_REPLY` payload に格納された user ID.
    """
    unpacked = struct.unpack("<i", body[_HEADER_SIZE : _HEADER_SIZE + 4])
    return cast("int", unpacked[0])


def _make_test_app(
    *,
    max_request_body_size: int = 1_048_576,
    packet_queue_max_size: int = 4096,
    broker: AsyncBroker | None = None,
    packet_dispatcher: PacketDispatcher | None = None,
) -> Starlette:
    """in-memory provider を持つ Bancho integration test application を生成する.

    Args:
        max_request_body_size (int): request body を処理する最大 byte 数.
        packet_queue_max_size (int): user ごとの packet queue に保持する最大 packet 数.
        broker (AsyncBroker | None): beatmap fetch task に使う broker.
            `None` なら既定 provider を使う.
        packet_dispatcher (PacketDispatcher | None): C2S packet dispatcher.
            `None` なら既定 provider を使う.

    Returns:
        Starlette: provider override を適用した lifespan 管理前の application.
    """
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
    """Default role を command-side の in-memory persistence へ保存する.

    Args:
        app (Starlette): lifespan 中の test application.

    Returns:
        None: login 用 role を保存して完了し, 呼び出し側へ値を返さない.
    """
    await seed_role(app, _ROLE_DEFAULT)


async def _seed_status_change_beatmap(app: Starlette) -> None:
    """Metadata が fresh で osu file が未取得の既知 beatmap を保存する.

    Args:
        app (Starlette): lifespan 中の test application.

    Returns:
        None: `STATUS_CHANGE` warmup 用の beatmapset を保存して完了し, 呼び出し側へ値を返さない.
    """
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
    """既知 beatmap へ利用可能な osu file attachment を保存する.

    Args:
        app (Starlette): lifespan 中の test application.

    Returns:
        None: beatmap file attachment を保存して完了し, 呼び出し側へ値を返さない.
    """
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
    """Capture log から指定 event name の entry だけを取り出す.

    Args:
        logs (list[EventDict]): structlog capture で取得した event entry.
        event_name (str): 抽出する `event` field の値.

    Returns:
        list[EventDict]: `event` field が指定値に一致する entry.
    """
    return [entry for entry in logs if entry.get("event") == event_name]


async def _resolve_services(
    app: Starlette,
) -> tuple[PacketDispatcher, PacketQueue, SessionStore, AuthService]:
    """Lifespan 後の DI container から polling test 用 service を解決する.

    Args:
        app (Starlette): lifespan 中の test application.

    Returns:
        tuple[PacketDispatcher, PacketQueue, SessionStore, AuthService]:
            packet dispatch, queue, session, authentication の service.
    """
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
    """Test user を登録して login token を取得する.

    Args:
        auth_service (AuthService): test user を登録する command service.
        client (TestClient): Bancho login request を送信する test client.

    Returns:
        str: successful login response の `cho-token` header 値.
    """
    _ = await auth_service.register(
        RegistrationForm(username="TestUser", email="t@e.com", password=_PASSWORD),
    )
    resp = client.post(_BANCHO_URL, content=_build_login_body())
    assert resp.status_code == _OK
    return resp.headers["cho-token"]


@final
class RecordingBeatmapFetchQueue:
    """beatmap fetch enqueue を記録する in-memory taskiq adapter.

    Attributes:
        broker (AsyncBroker): fetch task を即時実行する in-memory broker.
        enqueued_targets (list[BeatmapFetchTarget]): enqueue された fetch target の出現順 list.
        file_fetch_use_case (FetchBeatmapFileUseCase | None):
            file fetch task から実行する optional use case.
    """

    broker: AsyncBroker
    enqueued_targets: list[BeatmapFetchTarget]
    file_fetch_use_case: FetchBeatmapFileUseCase | None

    def __init__(self) -> None:
        """Fetch task を登録した記録用 broker と空の target list を初期化する."""
        self.broker = InMemoryBroker(await_inplace=True)
        self.enqueued_targets = []
        self.file_fetch_use_case = None

        @self.broker.task(task_name="fetch_beatmap_file")
        async def fetch_beatmap_file(target_type: str, target_key: str) -> None:
            """File fetch task の payload を target として記録し, 必要なら use case を実行する.

            Args:
                target_type (str): queue payload に含まれる fetch target の種別.
                target_key (str): queue payload に含まれる fetch target の識別値.

            Returns:
                None: target を記録し, optional use case 実行後に呼び出し側へ値を返さない.
            """
            target = BeatmapFetchTarget.from_queue_payload(
                target_type=target_type,
                target_key=target_key,
            )
            self.enqueued_targets.append(target)
            if self.file_fetch_use_case is not None:
                await self.file_fetch_use_case.execute(target)

        @self.broker.task(task_name="fetch_beatmap_metadata")
        async def fetch_beatmap_metadata(target_type: str, target_key: str) -> None:
            """Metadata fetch task の payload を target として記録する.

            Args:
                target_type (str): queue payload に含まれる fetch target の種別.
                target_key (str): queue payload に含まれる fetch target の識別値.

            Returns:
                None: target を記録して完了し, 呼び出し側へ値を返さない.
            """
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
    """login から C2S dispatch と S2C drain までの polling flow を検証する."""

    async def test_full_c2s_to_s2c_flow(self) -> None:
        """C2S handler が enqueue した payload が同じ polling response に現れる契約を検証する.

        `SEND_MESSAGE` handler が user queue へ byte 列を追加する.
        packet を含む polling response がその byte 列を返すことを確認する.

        Returns:
            None: C2S から S2C への delivery を検証して完了し, 呼び出し側へ値を返さない.
        """
        app = _make_test_app(packet_dispatcher=PacketDispatcher())
        user_id_ref: list[int] = []

        with TestClient(app, raise_server_exceptions=False) as client:
            dispatcher, packet_queue, session_store, auth_service = await _resolve_services(app)

            @dispatcher.register(ClientPacketID.SEND_MESSAGE)
            async def handler(_payload: bytes, *_a: object, **_kw: object) -> None:
                """Test 用 payload を現在の user の S2C queue へ追加する.

                Args:
                    _payload (bytes): dispatcher が decode した C2S payload.
                    *_a (object): handler contract の追加 positional value.
                    **_kw (object): handler contract の追加 keyword value.

                Returns:
                    None: fixed payload を queue へ追加して完了し, 呼び出し側へ値を返さない.
                """
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
    """`STATUS_CHANGE` による beatmap file warmup の polling contract を検証する."""

    async def test_status_change_by_id_requests_file_fetch_and_keeps_other_packets(self) -> None:
        """Beatmap ID の STATUS_CHANGE が file fetch と後続 packet を処理する契約を検証する.

        osu file が未取得の既知 beatmap を保存して `STATUS_CHANGE` と `PONG` を連結する.
        user stats response, fetch target, log event を確認する.

        Returns:
            None: warmup request と後続 packet 処理を検証して完了し, 呼び出し側へ値を返さない.
        """
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
        """Stable client の空文字 field を含む `STATUS_CHANGE` が user stats を返す契約を検証する.

        mode switch payload の空の status text と checksum を送信する.
        decode failure なしで user stats response が返ることを確認する.

        Returns:
            None: stable empty string compatibility を検証して完了し, 呼び出し側へ値を返さない.
        """
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
        """Checksum のみの `STATUS_CHANGE` が既知 beatmap の file fetch を要求する契約を検証する.

        beatmap ID を 0 にして uppercase checksum を送信する.
        checksum lookup で解決した既知 beatmap の fetch target を確認する.

        Returns:
            None: checksum fallback warmup を検証して完了し, 呼び出し側へ値を返さない.
        """
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
        """重複する `STATUS_CHANGE` が 1 件の pending file fetch state に収束する契約を検証する.

        pending fetch state の beatmap へ同じ status packet を 2 回送信する.
        enqueue は 2 回でも永続化された attempt count は 1 のままであることを確認する.

        Returns:
            None: repeated warmup の idempotent persistence を検証して完了する.
                呼び出し側へ値を返さない.
        """
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
        """Osu file が利用可能な `STATUS_CHANGE` が fetch を要求しない契約を検証する.

        file attachment 済み beatmap の status packet を送信する.
        user stats response と `already_available` log event を確認する.

        Returns:
            None: available file の warmup no-op を検証して完了し, 呼び出し側へ値を返さない.
        """
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
    """polling が session TTL を更新する契約を検証する."""

    async def test_session_exists_after_poll(self) -> None:
        """有効な token の polling 後も session が存在する契約を検証する.

        login で発行した token を送信して polling を実行する.
        session store がその token を保持することを確認する.

        Returns:
            None: session TTL refresh の結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _, _, session_store, auth_service = await _resolve_services(app)
            token = await _login_and_get_token(auth_service, client)
            _ = client.post(_BANCHO_URL, headers={"osu-token": token})
            assert await session_store.exists(token) is True


class TestInvalidTokenRejection:
    """無効な polling token の authentication failure 契約を検証する."""

    async def test_invalid_token_returns_auth_failed(self) -> None:
        """未知の `osu-token` が authentication failed login reply を返す契約を検証する.

        session store に存在しない token を送信する.
        `LOGIN_REPLY` payload が `AUTHENTICATION_FAILED` になることを確認する.

        Returns:
            None: invalid token response を検証して完了し, 呼び出し側へ値を返さない.
        """
        app = _make_test_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            _ = await _resolve_services(app)
            resp = client.post(_BANCHO_URL, headers={"osu-token": "bogus"})
            value = _extract_login_reply(resp.content)
            assert value == LoginResult.AUTHENTICATION_FAILED


class TestNoTokenFallsBackToLogin:
    """`osu-token` header がない request の login fallback 契約を検証する."""

    async def test_no_token_triggers_login(self) -> None:
        """Token header なしの credentials request が login flow を実行する契約を検証する.

        account を登録して raw login body だけを送信し, token header と正の login reply を確認する.

        Returns:
            None: header 不在時の login fallback を検証して完了し, 呼び出し側へ値を返さない.
        """
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
    """最大 request body size を超える polling request の契約を検証する."""

    async def test_oversized_body_returns_empty(self) -> None:
        """Size limit を超える request body が空 response を返す契約を検証する.

        最大 10 byte の application へ 20 byte の polling payload を送信する.
        packet 処理なしの空 body を確認する.

        Returns:
            None: oversized body response を検証して完了し, 呼び出し側へ値を返さない.
        """
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
    """破損した C2S header が S2C queue drain を妨げない契約を検証する."""

    async def test_corrupt_header_still_returns_s2c(self) -> None:
        """破損 C2S packet を含む polling が既存 S2C payload を返す契約を検証する.

        user queue へ byte 列を追加してから不完全な header を送信する.
        parse failure 後も queue の byte 列が response に現れることを確認する.

        Returns:
            None: corrupt packet 時の S2C drain を検証して完了し, 呼び出し側へ値を返さない.
        """
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
    """C2S handler の exception 後も後続 packet を処理する契約を検証する."""

    async def test_failing_handler_does_not_block_next(self) -> None:
        """失敗する C2S handler が次の handler の実行を阻害しない契約を検証する.

        `JOIN_CHANNEL` handler を意図的に失敗させる.
        同じ request の `SEND_MESSAGE` handler が結果を追加することを確認する.

        Returns:
            None: handler exception isolation を検証して完了し, 呼び出し側へ値を返さない.
        """
        app = _make_test_app(packet_dispatcher=PacketDispatcher())
        results: list[str] = []

        with TestClient(app, raise_server_exceptions=False) as client:
            dispatcher, _, _, auth_service = await _resolve_services(app)

            @dispatcher.register(ClientPacketID.JOIN_CHANNEL)
            async def failing(_payload: bytes, *_a: object, **_kw: object) -> None:
                """Dispatch failure を再現するために `RuntimeError` を送出する.

                Args:
                    _payload (bytes): dispatcher が decode した C2S payload.
                    *_a (object): handler contract の追加 positional value.
                    **_kw (object): handler contract の追加 keyword value.

                Returns:
                    None: 処理を完了し, 呼び出し側へ値を返さない.

                Raises:
                    RuntimeError: 後続 handler の処理継続を検証するために常に送出する.
                """
                msg = "boom"
                raise RuntimeError(msg)

            @dispatcher.register(ClientPacketID.SEND_MESSAGE)
            async def ok(_payload: bytes, *_a: object, **_kw: object) -> None:
                """前の handler failure 後に到達する C2S handler を記録する.

                Args:
                    _payload (bytes): dispatcher が decode した C2S payload.
                    *_a (object): handler contract の追加 positional value.
                    **_kw (object): handler contract の追加 keyword value.

                Returns:
                    None: handler 到達を記録して完了し, 呼び出し側へ値を返さない.
                """
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
    """packet queue の max size が古い packet を削除する契約を検証する."""

    async def test_oldest_trimmed_when_over_limit(self) -> None:
        """Queue limit 超過時に最新 packet だけを polling response へ残す契約を検証する.

        最大 3 packet の queue に 5 packet を enqueue して polling する.
        最後の 3 payload が出現順に返ることを確認する.

        Returns:
            None: oldest packet trimming を検証して完了し, 呼び出し側へ値を返さない.
        """
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
    """Valkey packet queue の concurrent drain が重複配送しない契約を検証する."""

    async def test_concurrent_drain_no_duplicates(self) -> None:
        """同時の `dequeue_all` が全 packet を 1 回だけ返す契約を検証する.

        100 packet を enqueue した Valkey queue を 3 coroutine で同時 drain する.
        非空 result が 1 件だけであることを確認する.

        Returns:
            None: concurrent drain の single delivery を検証して完了し, 呼び出し側へ値を返さない.

        Notes:
            `VALKEY_URL` が TCP 接続可能であることを test 開始時に要求する.
            作成した key は finally block で削除する.
        """
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
