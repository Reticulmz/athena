"""LoginHandler — POST / handler for osu! stable bancho login and polling.

Dispatches based on the ``osu-token`` header:
- Absent  -> login flow (parse body, authenticate, build S2C packet stream)
- Present -> polling flow (C2S parse → dispatch → S2C drain → response)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog
import structlog.contextvars
from starlette.responses import Response

from osu_server.domain.auth import LoginResponse, LoginResult
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.parsers.login import parse_login_request
from osu_server.transports.bancho.protocol.errors import PacketReadError
from osu_server.transports.bancho.protocol.reader import read_packets
from osu_server.transports.bancho.protocol.s2c.login import (
    channel_available,
    channel_info_complete,
    friends_list,
    login_permissions,
    login_reply,
    protocol_version,
    silence_info,
    user_presence,
    user_presence_bundle,
    user_stats,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.infrastructure.country.interfaces import CountryResolver
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.session_store import SessionStore
    from osu_server.services.auth_service import AuthService
    from osu_server.transports.bancho.dispatch import PacketDispatcher

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_PROTOCOL_VERSION = 19


class LoginHandler:
    """Starlette handler for ``POST /``.

    Receives DI dependencies in ``__init__`` and acts as a callable ASGI
    endpoint via ``__call__``.
    """

    _auth_service: AuthService
    _session_store: SessionStore
    _country_resolver: CountryResolver
    _packet_queue: PacketQueue
    _packet_dispatcher: PacketDispatcher
    _session_ttl: int
    _max_request_body_size: int

    def __init__(
        self,
        *,
        auth_service: AuthService,
        session_store: SessionStore,
        country_resolver: CountryResolver,
        packet_queue: PacketQueue,
        packet_dispatcher: PacketDispatcher,
        session_ttl: int = 300,
        max_request_body_size: int = 1_048_576,
    ) -> None:
        self._auth_service = auth_service
        self._session_store = session_store
        self._country_resolver = country_resolver
        self._packet_queue = packet_queue
        self._packet_dispatcher = packet_dispatcher
        self._session_ttl = session_ttl
        self._max_request_body_size = max_request_body_size

    async def __call__(self, request: Request) -> Response:
        """Dispatch to login or polling based on ``osu-token`` header."""
        if "osu-token" in request.headers:
            return await self._handle_polling(request)
        return await self._handle_login(request)

    # ── Login flow ───────────────────────────────────────────────────

    async def _handle_login(self, request: Request) -> Response:
        """Parse login request, authenticate, and build S2C packet stream."""
        body = await request.body()

        try:
            login_request = parse_login_request(body)
        except ValueError:
            logger.warning("login_parse_failed")
            return Response(
                content=login_reply(LoginResult.AUTHENTICATION_FAILED),
            )

        country = self._country_resolver.resolve(request.headers)
        result = await self._auth_service.login(login_request, country=country)

        if isinstance(result, LoginResult):
            return Response(content=login_reply(result))

        _ = structlog.contextvars.bind_contextvars(
            user=result.user.username,
            user_id=result.user.id,
        )

        stream = _build_login_response_stream(result)
        return Response(
            content=stream,
            headers={"cho-token": result.token},
        )

    # ── Polling flow ─────────────────────────────────────────────────

    async def _handle_polling(self, request: Request) -> Response:
        """C2S → dispatch → S2C drain pipeline.

        Processing order:
        1. Body size check (reject if over limit)
        2. Session validation (AUTH_FAILED if invalid)
        3. Session TTL refresh
        4. C2S packet parse and sequential dispatch (if body non-empty)
        5. S2C packet queue drain
        6. Packet queue TTL refresh
        7. Response (concatenated S2C bytes)
        """
        start = time.monotonic()
        token = request.headers["osu-token"]
        body = await request.body()

        # 1. Body size check
        if len(body) > self._max_request_body_size:
            logger.warning(
                "polling_body_too_large",
                size=len(body),
                limit=self._max_request_body_size,
            )
            return Response(content=b"")

        # 2. Session validation
        session = await self._session_store.get(token)
        if session is None:
            return Response(content=login_reply(LoginResult.AUTHENTICATION_FAILED))

        user_id = int(session["user_id"])  # pyright: ignore[reportArgumentType]

        # 3. Session TTL refresh
        _ = await self._session_store.refresh(token)

        # 4. C2S parse and dispatch
        c2s_count = 0
        if body:
            try:
                packets = read_packets(body)
            except PacketReadError:
                logger.error("c2s_parse_error", exc_info=True)
                packets = []

            for packet_id, payload in packets:
                c2s_count += 1
                try:
                    await self._packet_dispatcher.dispatch(packet_id, payload)
                except Exception:
                    logger.error(
                        "c2s_handler_error",
                        packet=packet_id.name,
                        payload_size=len(payload),
                        exc_info=True,
                    )

        # 5. S2C drain
        response_data = await self._packet_queue.dequeue_all(user_id)

        # 6. Queue TTL refresh
        await self._packet_queue.refresh_ttl(user_id, self._session_ttl)

        # 7. Polling statistics
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "polling_complete",
            c2s_count=c2s_count,
            s2c_bytes=len(response_data),
            elapsed_ms=round(elapsed_ms, 2),
        )

        return Response(content=response_data)


# ── Packet stream builder ────────────────────────────────────────────


def _build_login_response_stream(
    login_response: LoginResponse,
) -> bytes:
    """Assemble the S2C packet stream for a successful login.

    Calls 10 S2C builder functions and concatenates their output.
    """
    user = login_response.user
    session = login_response.session_data
    client_flags = PermissionService.to_client_flags(login_response.privileges)
    country_id = country_code_to_id(login_response.country)

    packets: list[bytes] = [
        # 1. login_reply with positive user_id
        login_reply(user.id),
        # 2. protocol_version
        protocol_version(_PROTOCOL_VERSION),
        # 3. login_permissions (client flags)
        login_permissions(int(client_flags)),
        # 4. user_presence
        user_presence(
            user_id=user.id,
            username=user.username,
            timezone=session.utc_offset + 24,
            country_id=country_id,
            permissions=int(client_flags),
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        ),
        # 5. user_stats (initial values)
        user_stats(
            user_id=user.id,
            status=0,
            status_text="",
            beatmap_md5="",
            mods=0,
            play_mode=0,
            beatmap_id=0,
            ranked_score=0,
            accuracy=0.0,
            play_count=0,
            total_score=0,
            rank=0,
            pp=0,
        ),
        # 6. channel_available
        channel_available(name="#osu", topic="", user_count=0),
        # 7. channel_info_complete
        channel_info_complete(),
        # 8. friends_list (empty)
        friends_list([]),
        # 9. silence_info (0 seconds)
        silence_info(0),
        # 10. user_presence_bundle
        user_presence_bundle([user.id]),
    ]

    return b"".join(packets)
