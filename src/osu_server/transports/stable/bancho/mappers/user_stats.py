"""Current user stats と system bot を Stable Bancho USER_STATS packet へ変換する."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable import DEFAULT_STABLE_USER_STATUS, StableUserStatus
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats

if TYPE_CHECKING:
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.domain.scores.user_stats import UserCurrentStats

_STABLE_DEFAULT_SCORE = 0
_STABLE_DEFAULT_ACCURACY = 0.0
_STABLE_DEFAULT_PLAY_COUNT = 0
_STABLE_DEFAULT_RANK = 0
_STABLE_DEFAULT_PP = 0


def stable_user_stats_packet(
    *,
    user_id: int,
    current_stats: UserCurrentStats | None,
    play_mode: int | None = None,
    status: StableUserStatus | None = None,
) -> bytes:
    """指定した current stats を Stable Bancho USER_STATS packet へ変換する.

    Args:
        user_id (int): packet の対象 user ID.
        current_stats (UserCurrentStats | None): current stats. None なら default 値.
        play_mode (int | None): stable mode wire 値. None なら status の mode を使う.
        status (StableUserStatus | None): STATUS_CHANGE の status fields. None なら default.

    Returns:
        bytes: complete USER_STATS packet.

    Notes:
        status と play_mode が None の場合は osu! standard mode を使う.
        PP は ROUND_HALF_UP で整数化し, uint16 clamp は packet builder に委ねる.
    """
    stable_status = status or DEFAULT_STABLE_USER_STATUS
    stable_play_mode = play_mode if play_mode is not None else stable_status.play_mode
    return user_stats(
        user_id=user_id,
        status=stable_status.status,
        status_text=stable_status.status_text,
        beatmap_md5=stable_status.beatmap_md5,
        mods=stable_status.mods,
        play_mode=stable_play_mode,
        beatmap_id=stable_status.beatmap_id,
        ranked_score=(
            current_stats.ranked_score if current_stats is not None else _STABLE_DEFAULT_SCORE
        ),
        accuracy=(
            current_stats.accuracy if current_stats is not None else _STABLE_DEFAULT_ACCURACY
        ),
        play_count=(
            current_stats.play_count if current_stats is not None else _STABLE_DEFAULT_PLAY_COUNT
        ),
        total_score=(
            current_stats.total_score if current_stats is not None else _STABLE_DEFAULT_SCORE
        ),
        rank=(
            current_stats.global_rank
            if current_stats is not None and current_stats.global_rank is not None
            else _STABLE_DEFAULT_RANK
        ),
        pp=(_stable_pp(current_stats.pp) if current_stats is not None else _STABLE_DEFAULT_PP),
    )


def bot_user_stats_packet(
    bot_identity: SystemUserIdentity | None = None,
    *,
    play_mode: int | None = None,
) -> bytes:
    """指定した system bot identity の Stable Bancho USER_STATS packet を構築する.

    Args:
        bot_identity (SystemUserIdentity | None): system bot. None なら BanchoBot.
        play_mode (int | None): bot を表示する stable mode wire 値. None なら osu! mode.

    Returns:
        bytes: system bot の default stats を持つ USER_STATS packet.

    Notes:
        stable protocol では user を複数 mode に同時所属させられない.
        呼び出し側は request context に合う単一 mode を指定する.
        BanchoBot は常時 online な valid target として扱う.
    """
    bot = bot_identity or BANCHO_BOT_IDENTITY
    return stable_user_stats_packet(
        user_id=bot.user_id,
        current_stats=None,
        play_mode=play_mode,
    )


def _stable_pp(pp: Decimal) -> int:
    """与えられた performance point を stable wire 用の整数へ丸める.

    Args:
        pp (Decimal): current stats が保持する performance point.

    Returns:
        int: ROUND_HALF_UP で丸めた stable packet 用の整数.
    """
    return int(pp.to_integral_value(rounding=ROUND_HALF_UP))


__all__ = ["bot_user_stats_packet", "stable_user_stats_packet"]
