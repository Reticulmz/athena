"""Stable user status state store の Valkey 実装を提供する module."""

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
    """Stable current status を TTL 付き JSON として Valkey に保存する state store.

    Attributes:
        _client (GlideClient): status JSON と TTL を操作する Valkey client.
        _ttl (int): set_status で新規保存する status の TTL 秒数.
        _prefix (str): 環境または test を分離する key prefix.

    Notes:
        status key は `{prefix}stable_user_status:{user_id}:status` を使用する.
        get_statuses は user id 群を一度の MGET で読み,decode 不能な値を返却 mapping から除外する.
    """

    def __init__(
        self,
        client: GlideClient,
        *,
        ttl: int = 300,
        key_prefix: str = "",
    ) -> None:
        """Valkey client と status TTL を持つ state store を初期化する.

        Args:
            client (GlideClient): JSON status の保存と取得を行う Valkey client.
            ttl (int): set_status で設定する status の TTL 秒数.
            key_prefix (str): key 名前空間を分離する任意の prefix.
        """
        self._client: GlideClient = client
        self._ttl: int = ttl
        self._prefix: str = key_prefix

    def _status_key(self, user_id: int) -> str:
        """User の stable status JSON に対応する Valkey key を組み立てる.

        Args:
            user_id (int): key に埋め込む user id.

        Returns:
            str: `{prefix}stable_user_status:{user_id}:status` 形式の status key.
        """
        return f"{self._prefix}stable_user_status:{user_id}:status"

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """User の current status fields を configured TTL 付きで保存する.

        Args:
            user_id (int): 保存先 user id.
            status (StableUserStatus): JSON へ encode する stable client status.

        Returns:
            None: status の SET と TTL 設定が完了したことを表す.
        """
        _ = await self._client.set(
            self._status_key(user_id),
            _encode_status(status),
            expiry=ExpirySet(ExpiryType.SEC, self._ttl),
        )

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """複数 user の current status fields を一度の MGET で返す.

        Args:
            user_ids (tuple[int, ...]): 取得対象の user id 群.

        Returns:
            dict[int, StableUserStatus]: decode できた保存済み user id だけを含む status mapping.

        Notes:
            user_ids が空なら Valkey を呼ばず空 mapping を返す.
        """
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
        """User の current play mode を status JSON 内に TTL 付きで保存する.

        Args:
            user_id (int): 保存先 user id.
            play_mode (int): stable protocol の current play mode 値.

        Returns:
            None: updated status の保存完了を表す.

        Notes:
            status が未保存なら DEFAULT_STABLE_USER_STATUS を基準に作成する.
        """
        current = (await self.get_statuses((user_id,))).get(
            user_id,
            DEFAULT_STABLE_USER_STATUS,
        )
        await self.set_status(user_id, current.with_play_mode(play_mode))

    async def get_play_mode(self, user_id: int) -> int | None:
        """User の current play mode を返す.

        Args:
            user_id (int): 取得対象の user id.

        Returns:
            int | None: 保存済み play mode.status が未保存または decode 不能なら None.
        """
        status = (await self.get_statuses((user_id,))).get(user_id)
        return None if status is None else status.play_mode

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """複数 user の current play mode を user id keyed mapping で返す.

        Args:
            user_ids (tuple[int, ...]): 取得対象の user id 群.

        Returns:
            dict[int, int]: decode できた保存済み user id だけを含む play mode mapping.
        """
        return {
            user_id: status.play_mode
            for user_id, status in (await self.get_statuses(user_ids)).items()
        }

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """保存済み current status の TTL を session TTL と同期する.

        Args:
            user_id (int): TTL を更新する user id.
            ttl (int): session と同期する有効期限の秒数.

        Returns:
            None: EXPIRE 実行の完了を表す.

        Notes:
            status key が未存在の場合も新しい status は作成しない.
        """
        _ = await self._client.expire(self._status_key(user_id), ttl)


def _encode_status(status: StableUserStatus) -> str:
    """Stable user status を Valkey 保存用の compact JSON へ変換する.

    Args:
        status (StableUserStatus): JSON へ serialise する stable client status.

    Returns:
        str: status,status_text,beatmap_md5,mods,play_mode,beatmap_id を持つ JSON string.
    """
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
    """Valkey raw value を検証済み StableUserStatus へ decode する.

    Args:
        raw (object): MGET が返した raw status value.

    Returns:
        StableUserStatus | None: 正しい JSON object なら status,未存在または不正値なら None.
    """
    raw_text = _raw_status_text(raw)
    if raw_text is None:
        return None

    try:
        decoded = cast("object", loads(raw_text))
    except JSONDecodeError, TypeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return _decode_status_mapping(cast("dict[object, object]", decoded))


def _raw_status_text(raw: object) -> str | None:
    """Raw Valkey status value を JSON decode 用 text へ正規化する.

    Args:
        raw (object): str,bytes,None,または別型の raw status value.

    Returns:
        str | None: str はそのまま,UTF-8 bytes は decoded text,それ以外または不正 bytes は None.
    """
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
    """JSON object payload を required field を持つ StableUserStatus へ変換する.

    Args:
        payload (dict[object, object]): JSON decode 済みの raw mapping.

    Returns:
        StableUserStatus | None: すべての required field が正しい型なら status,それ以外は None.
    """
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
    """Bool を除外して raw value が integer かを検証する.

    Args:
        raw (object): 整数として検証する JSON field value.

    Returns:
        int | None: bool ではない integer ならその値,それ以外は None.
    """
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


__all__ = ["ValkeyStableUserStatusStore"]
