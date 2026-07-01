"""Stable bancho UserStats packet mapping."""

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
    """current stats を stable USER_STATS packet に mapping する.

    引数:
        user_id: packet の対象 user id.
        current_stats: transport-neutral current stats. None の場合は stable-safe
            default values を使う.
        play_mode: stable Mode wire 値. 未指定時は status の mode を使い、
            status も未指定の場合は osu! standard を使う.
        status: STATUS_CHANGE 由来の stable status fields. 未指定時は
            login/STATS_REQUEST 向けの default status fields を使う.

    戻り値:
        Stable USER_STATS の complete packet.

    例外:
        wire type の範囲外値は既存 packet builder の pack error として送出する.

    制約:
        status 未指定時は status fields に default values を使う. PP は stable
        int に ROUND_HALF_UP で丸め、最終的な uint16 clamp は packet builder に委ねる.
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
    """BanchoBot 用の stable USER_STATS packet を構築する。

    引数:
        bot_identity: packet に載せる system user identity。未指定時は BanchoBot。
        play_mode: Bot を表示する stable mode wire 値。未指定時は osu!。

    戻り値:
        Bancho S2C USER_STATS packet bytes。

    例外:
        wire type の範囲外値は既存 packet builder の pack error として送出する。

    制約:
        Stable protocol は user を複数 mode に同時所属させられないため、呼び出し元が
        request context に合った単一 mode を指定する。本家 bancho.py と同じく
        Bot は常時 online な valid target として扱う。
    """
    bot = bot_identity or BANCHO_BOT_IDENTITY
    return stable_user_stats_packet(
        user_id=bot.user_id,
        current_stats=None,
        play_mode=play_mode,
    )


def _stable_pp(pp: Decimal) -> int:
    return int(pp.to_integral_value(rounding=ROUND_HALF_UP))


__all__ = ["bot_user_stats_packet", "stable_user_stats_packet"]
