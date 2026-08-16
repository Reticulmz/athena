"""Beatmap domain modelの共通不変条件を検証するmodule."""

from typing import TYPE_CHECKING

from osu_server.domain.beatmaps.states import BeatmapRankStatus, LocalBeatmapStatus
from osu_server.shared.checksums import MD5_HEX_LENGTH, is_lowercase_md5_hexdigest

if TYPE_CHECKING:
    from collections.abc import Iterable


def validate_beatmapset_child_ownership(
    child_beatmapset_ids: Iterable[int],
    beatmapset_id: int,
    *,
    mismatch_message: str,
) -> None:
    """全childのbeatmapset IDが親IDと一致することを検証する.

    Args:
        child_beatmapset_ids (Iterable[int]): 検証するchildのbeatmapset ID群.
        beatmapset_id (int): 親beatmapsetのID.
        mismatch_message (str): 所有ID不一致時のerror message.

    Returns:
        None: 全childの所有IDを検証して完了する.

    Raises:
        ValueError: childのbeatmapset IDが親IDと一致しない場合.
    """
    for child_beatmapset_id in child_beatmapset_ids:
        if child_beatmapset_id != beatmapset_id:
            raise ValueError(mismatch_message)


def validate_md5(checksum_md5: str) -> None:
    """MD5 checksumが小文字16進数の固定長値か検証する.

    Args:
        checksum_md5 (str): 検証するMD5 checksum.

    Returns:
        None: checksum_md5が有効であることを確認して完了する.

    Raises:
        ValueError: checksum_md5が32文字の小文字16進数でない場合.
    """
    if not is_lowercase_md5_hexdigest(checksum_md5):
        msg = f"checksum_md5 must be a {MD5_HEX_LENGTH}-character lowercase hexadecimal string"
        raise ValueError(msg)


def validate_local_override(status: object) -> None:
    """ローカルstatus上書きに許可された値だけを受け入れる.

    Args:
        status (object): 検証するローカルstatus上書き値.

    Returns:
        None: statusがLocalBeatmapStatusまたはNoneであることを確認して完了する.

    Raises:
        TypeError: statusがLocalBeatmapStatusまたはNoneでない場合.
        ValueError: statusが公式status専用のAPPROVEDである場合.
    """
    if status is None:
        return
    if status is BeatmapRankStatus.APPROVED:
        msg = "Approved cannot be used as a local override"
        raise ValueError(msg)
    if not isinstance(status, LocalBeatmapStatus):
        msg = "local_status_override must be a LocalBeatmapStatus or None"
        raise TypeError(msg)
