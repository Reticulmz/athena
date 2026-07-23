"""stable BanchoのSTATS_REQUEST C2S packetをcurrent statsへ適応する."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.services.queries.identity import GetActiveSessionsByUserIdsQueryInput
from osu_server.services.queries.scores import CurrentUserStatsQueryInput
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.mappers.user_stats import (
    bot_user_stats_packet,
    stable_user_stats_packet,
)
from osu_server.transports.stable.bancho.protocol.c2s import parse_stats_request_payload
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.domain.compatibility.stable import StableUserStatus
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.domain.scores.user_stats import UserCurrentStats
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.identity import GetActiveSessionsByUserIdsQuery
    from osu_server.services.queries.scores import CurrentUserStatsQuery

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class StatsRequestHandler(HandlerGroup):
    """STATS_REQUESTをvisible online userのUSER_STATS packetへ変換する.

    Attributes:
        _current_user_stats_query (CurrentUserStatsQuery): userのcurrent statsを取得するquery.
        _packet_queue (PacketQueue): USER_STATS packetをrequesterへenqueueするqueue.
        _stable_user_status_store (StableUserStatusStore | None):
            user statusとplay modeを取得するstore.
        _active_sessions_by_user_ids_query (GetActiveSessionsByUserIdsQuery | None):
            online可視性を確認するquery.
        _bot_identity (SystemUserIdentity): STATS_REQUESTで返すBanchoBot identity.
    """

    _current_user_stats_query: CurrentUserStatsQuery
    _packet_queue: PacketQueue
    _stable_user_status_store: StableUserStatusStore | None
    _active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery | None
    _bot_identity: SystemUserIdentity

    def __init__(
        self,
        *,
        current_user_stats_query: CurrentUserStatsQuery,
        packet_queue: PacketQueue,
        stable_user_status_store: StableUserStatusStore | None = None,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery | None = None,
        bot_identity: SystemUserIdentity | None = None,
    ) -> None:
        """STATS_REQUESTを処理する依存を初期化する.

        Args:
            current_user_stats_query (CurrentUserStatsQuery): current statsを取得するquery.
            packet_queue (PacketQueue): S2C packetをenqueueするqueue.
            stable_user_status_store (StableUserStatusStore | None): status読取用のoptional store.
            active_sessions_by_user_ids_query (GetActiveSessionsByUserIdsQuery | None):
                可視性確認用のoptional query.
            bot_identity (SystemUserIdentity | None): statsを返すBanchoBot identity.
                Noneなら既定値を使う.
        """
        self._current_user_stats_query = current_user_stats_query
        self._packet_queue = packet_queue
        self._stable_user_status_store = stable_user_status_store
        self._active_sessions_by_user_ids_query = active_sessions_by_user_ids_query
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY

    @handles(ClientPacketID.STATS_REQUEST)
    async def handle_stats_request(self, payload: bytes, user_id: int) -> None:
        """STATS_REQUESTのvisible targetへ対応するUSER_STATS packetを返す.

        Args:
            payload (bytes): target user ID群を含むSTATS_REQUEST payload.
            user_id (int): statsを要求した認証済みuserのID.

        Returns:
            None: 取得できたvisible targetのUSER_STATS packetをenqueueして値を返さずに完了する.

        Notes:
            requester自身、offline user、leaderboard非公開userはstats queryの前に除外する。
        """
        requested_user_ids = _parse_stats_request(payload)
        if requested_user_ids is None:
            return

        lookup_user_ids = tuple(
            dict.fromkeys(
                requested_user_id
                for requested_user_id in requested_user_ids
                if requested_user_id != user_id
            )
        )
        if len(lookup_user_ids) == 0:
            return

        visible_user_ids = await self._visible_online_user_ids(lookup_user_ids)
        if len(visible_user_ids) == 0:
            return

        stats_user_ids = tuple(
            visible_user_id
            for visible_user_id in visible_user_ids
            if visible_user_id != self._bot_identity.user_id
        )
        statuses_by_user_id = await self._statuses_by_user_id(stats_user_ids)
        play_modes_by_user_id = _play_modes_by_user_id(statuses_by_user_id)
        stats_by_user_id = await self._stats_by_user_id(
            stats_user_ids,
            play_modes_by_user_id=play_modes_by_user_id,
        )
        requester_play_mode = await self._requester_play_mode(user_id)

        packets: list[bytes] = []
        for requested_user_id in visible_user_ids:
            if requested_user_id == self._bot_identity.user_id:
                packets.append(
                    bot_user_stats_packet(
                        self._bot_identity,
                        play_mode=requester_play_mode,
                    )
                )
                continue
            stats = stats_by_user_id.get(requested_user_id)
            if stats is not None:
                packets.append(
                    stable_user_stats_packet(
                        user_id=requested_user_id,
                        current_stats=stats,
                        play_mode=_play_mode_for_user(
                            requested_user_id,
                            play_modes_by_user_id,
                        ),
                        status=statuses_by_user_id.get(requested_user_id),
                    )
                )
        packets_tuple = tuple(packets)
        if len(packets_tuple) == 0:
            return

        await self._packet_queue.enqueue(user_id, *packets_tuple)

    async def _visible_online_user_ids(self, user_ids: tuple[int, ...]) -> tuple[int, ...]:
        """onlineかつleaderboard表示可能なtarget user IDを絞り込む.

        Args:
            user_ids (tuple[int, ...]): deduplicate済みのSTATS_REQUEST target user ID群.

        Returns:
            tuple[int, ...]: statsを返せるvisible online user ID群. query失敗時は空tuple.

        Notes:
            BanchoBotはactive sessionを持たないため常に保持する。
        """
        bot_user_id = self._bot_identity.user_id
        session_user_ids = tuple(user_id for user_id in user_ids if user_id != bot_user_id)
        if self._active_sessions_by_user_ids_query is None:
            return user_ids
        try:
            result = await self._active_sessions_by_user_ids_query.execute(
                GetActiveSessionsByUserIdsQueryInput(user_ids=session_user_ids)
            )
        except Exception:
            logger.exception(
                "stable_stats_request_active_sessions_read_failed",
                requested_user_ids=user_ids,
            )
            return ()

        visible_user_id_set = {
            session.user_id
            for session in result.sessions
            if is_leaderboard_visible_user(session.privileges)
        }
        return tuple(
            user_id
            for user_id in user_ids
            if user_id == bot_user_id or user_id in visible_user_id_set
        )

    async def _stats_by_user_id(
        self,
        user_ids: tuple[int, ...],
        *,
        play_modes_by_user_id: Mapping[int, int],
    ) -> dict[int, UserCurrentStats]:
        """Play mode単位でcurrent statsを取得してuser IDへ対応付ける.

        Args:
            user_ids (tuple[int, ...]): statsを取得するvisible human user ID群.
            play_modes_by_user_id (Mapping[int, int]): user IDからtargetのstable play modeへの対応.

        Returns:
            dict[int, UserCurrentStats]: 取得できたcurrent statsのuser ID対応.

        Notes:
            一つのplay modeのqueryが失敗しても、他のplay modeの結果は保持する。
        """
        stats_by_user_id: dict[int, UserCurrentStats] = {}
        for play_mode, scoped_user_ids in _user_ids_by_play_mode(
            user_ids,
            play_modes_by_user_id,
        ).items():
            ruleset = _ruleset_for_play_mode(play_mode)
            try:
                result = await self._current_user_stats_query.execute(
                    CurrentUserStatsQueryInput(
                        user_ids=scoped_user_ids,
                        ruleset=ruleset,
                        playstyle=Playstyle.VANILLA,
                    )
                )
            except Exception:
                logger.exception(
                    "stable_stats_request_read_failed",
                    requested_user_ids=scoped_user_ids,
                    play_mode=play_mode,
                )
                continue
            stats_by_user_id.update(result.stats_by_user_id)
        return stats_by_user_id

    async def _statuses_by_user_id(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """Target userの保存済みstable statusを取得する.

        Args:
            user_ids (tuple[int, ...]): statusを取得するhuman user ID群.

        Returns:
            dict[int, StableUserStatus]: 取得できたuser statusのuser ID対応.
                store未設定または失敗時は空dict.
        """
        if self._stable_user_status_store is None:
            return {}
        try:
            return await self._stable_user_status_store.get_statuses(user_ids)
        except Exception:
            logger.exception(
                "stable_stats_request_status_read_failed", requested_user_ids=user_ids
            )
            return {}

    async def _requester_play_mode(self, user_id: int) -> int:
        """requesterへ表示するBanchoBotのstable play modeを取得する.

        Args:
            user_id (int): STATS_REQUESTを送信したuserのID.

        Returns:
            int: 正規化済みstable play mode. statusがないか読取失敗時はosu mode.
        """
        if self._stable_user_status_store is None:
            return StableMode.Osu.value
        try:
            play_mode = await self._stable_user_status_store.get_play_mode(user_id)
        except Exception:
            logger.exception(
                "stable_stats_requester_status_read_failed",
                user_id=user_id,
            )
            return StableMode.Osu.value
        return _stable_play_mode(play_mode)


def _parse_stats_request(payload: bytes) -> tuple[int, ...] | None:
    """STATS_REQUEST payloadを安全にparseする.

    Args:
        payload (bytes): target user ID群を含むC2S packet payload.

    Returns:
        tuple[int, ...] | None: parseしたtarget user ID群. payloadが不正な場合はNone.
    """
    try:
        return parse_stats_request_payload(payload)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet="STATS_REQUEST",
            payload_size=len(payload),
            reason=str(exc),
        )
        return None


def _user_ids_by_play_mode(
    user_ids: tuple[int, ...],
    play_modes_by_user_id: Mapping[int, int],
) -> dict[int, tuple[int, ...]]:
    """User ID群を有効なstable play modeごとにgroup化する.

    Args:
        user_ids (tuple[int, ...]): group化するtarget user ID群.
        play_modes_by_user_id (Mapping[int, int]): user IDから保存済みmodeへの対応.

    Returns:
        dict[int, tuple[int, ...]]: 正規化済みplay modeから対象user ID群への対応.
    """
    grouped: dict[int, list[int]] = defaultdict(list)
    for user_id in user_ids:
        grouped[_play_mode_for_user(user_id, play_modes_by_user_id)].append(user_id)
    return {play_mode: tuple(scoped_user_ids) for play_mode, scoped_user_ids in grouped.items()}


def _play_modes_by_user_id(
    statuses_by_user_id: Mapping[int, StableUserStatus],
) -> dict[int, int]:
    """Stable statusのplay modeをuser IDごとのmappingへ変換する.

    Args:
        statuses_by_user_id (Mapping[int, StableUserStatus]): user IDからstable statusへの対応.

    Returns:
        dict[int, int]: user IDからstatusに保存されたplay modeへの対応.
    """
    return {user_id: status.play_mode for user_id, status in statuses_by_user_id.items()}


def _play_mode_for_user(
    user_id: int,
    play_modes_by_user_id: Mapping[int, int],
) -> int:
    """userのplay modeを取得してstable modeとして正規化する.

    Args:
        user_id (int): modeを選択するtarget user ID.
        play_modes_by_user_id (Mapping[int, int]): user IDから保存済みmodeへの対応.

    Returns:
        int: 有効なstable play mode. 値がないか不正な場合はosu mode.
    """
    play_mode = play_modes_by_user_id.get(user_id, StableMode.Osu.value)
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


def _ruleset_for_play_mode(play_mode: int) -> Ruleset:
    """Stable play modeに対応するRulesetを返す.

    Args:
        play_mode (int): stable clientから得たmode値.

    Returns:
        Ruleset: 対応するRuleset. 不正な値の場合はOSU ruleset.
    """
    try:
        return Ruleset(play_mode)
    except ValueError:
        return Ruleset.OSU


def _stable_play_mode(play_mode: int | None) -> int:
    """optionalなplay modeを有効なstable modeへ正規化する.

    Args:
        play_mode (int | None): status storeから得た可能性のあるmode値.

    Returns:
        int: 有効なstable play mode. Noneまたは不正値の場合はosu mode.
    """
    if play_mode is None:
        return StableMode.Osu.value
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


__all__ = ["StatsRequestHandler"]
