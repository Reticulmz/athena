"""Valkey-backed stable user status store."""

from __future__ import annotations

from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, cast

from glide_shared.commands.core_options import ExpirySet, ExpiryType

from osu_server.domain.compatibility.stable import (
    DEFAULT_STABLE_USER_STATUS,
    StableUserStatus,
)

if TYPE_CHECKING:
    from glide import GlideClient, TEncodable


class ValkeyStableUserStatusStore:
    """Stable current status を Valkey に保存する。"""

    def __init__(
        self,
        client: GlideClient,
        *,
        ttl: int = 300,
        key_prefix: str = "",
    ) -> None:
        self._client: GlideClient = client
        self._ttl: int = ttl
        self._prefix: str = key_prefix

    def _status_key(self, user_id: int) -> str:
        return f"{self._prefix}stable_user_status:{user_id}:status"

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """指定 user の current status fields を TTL 付きで保存する。"""
        _ = await self._client.set(
            self._status_key(user_id),
            _encode_status(status),
            expiry=ExpirySet(ExpiryType.SEC, self._ttl),
        )

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """複数 user の current status fields を返す。"""
        if len(user_ids) == 0:
            return {}

        keys: list[TEncodable] = [self._status_key(user_id) for user_id in user_ids]
        raws = await self._client.mget(keys)
        result: dict[int, StableUserStatus] = {}
        for user_id, raw in zip(user_ids, raws, strict=True):
            status = _decode_status(raw)
            if status is not None:
                result[user_id] = status
        return result

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """指定 user の current play mode を TTL 付きで保存する。"""
        current = (await self.get_statuses((user_id,))).get(
            user_id,
            DEFAULT_STABLE_USER_STATUS,
        )
        await self.set_status(user_id, current.with_play_mode(play_mode))

    async def get_play_mode(self, user_id: int) -> int | None:
        """指定 user の current play mode を返す。"""
        status = (await self.get_statuses((user_id,))).get(user_id)
        return None if status is None else status.play_mode

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """複数 user の current play mode を返す。"""
        return {
            user_id: status.play_mode
            for user_id, status in (await self.get_statuses(user_ids)).items()
        }

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """保存済み current status の TTL を更新する。"""
        _ = await self._client.expire(self._status_key(user_id), ttl)


def _encode_status(status: StableUserStatus) -> str:
    return dumps(
        {
            "status": status.status,
            "status_text": status.status_text,
            "beatmap_md5": status.beatmap_md5,
            "mods": status.mods,
            "play_mode": status.play_mode,
            "beatmap_id": status.beatmap_id,
        },
        separators=(",", ":"),
    )


def _decode_status(raw: object) -> StableUserStatus | None:
    raw_text = _raw_status_text(raw)
    if raw_text is None:
        return None

    try:
        decoded = cast("object", loads(raw_text))
    except (JSONDecodeError, TypeError):
        return None
    if not isinstance(decoded, dict):
        return None
    return _decode_status_mapping(cast("dict[object, object]", decoded))


def _raw_status_text(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, bytes):
        return None
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return None


def _decode_status_mapping(payload: dict[object, object]) -> StableUserStatus | None:
    status = _decode_int(payload.get("status"))
    status_text = payload.get("status_text")
    beatmap_md5 = payload.get("beatmap_md5")
    mods = _decode_int(payload.get("mods"))
    play_mode = _decode_int(payload.get("play_mode"))
    beatmap_id = _decode_int(payload.get("beatmap_id"))
    if (
        status is None
        or not isinstance(status_text, str)
        or not isinstance(beatmap_md5, str)
        or mods is None
        or play_mode is None
        or beatmap_id is None
    ):
        return None
    return StableUserStatus(
        status=status,
        status_text=status_text,
        beatmap_md5=beatmap_md5,
        mods=mods,
        play_mode=play_mode,
        beatmap_id=beatmap_id,
    )


def _decode_int(raw: object) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


__all__ = ["ValkeyStableUserStatusStore"]
