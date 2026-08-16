"""Beatmap metadata/file取得対象とqueue payloadを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps.states import BeatmapFetchState


class BeatmapFetchTargetKind(Enum):
    """Beatmap domainが所有するfetch target encodingを表す閉集合.

    Attributes:
        METADATA_BY_BEATMAP_ID (str): beatmap IDでmetadataを取得するtarget.
        METADATA_BY_BEATMAPSET_ID (str): beatmapset IDでmetadataを取得するtarget.
        METADATA_BY_CHECKSUM (str): MD5 checksumでmetadataを取得するtarget.
        FILE_BY_BEATMAP_ID (str): beatmap IDでosu fileを取得するtarget.
    """

    METADATA_BY_BEATMAP_ID = "metadata:beatmap"
    METADATA_BY_BEATMAPSET_ID = "metadata:beatmapset"
    METADATA_BY_CHECKSUM = "metadata:checksum"
    FILE_BY_BEATMAP_ID = "file:beatmap"


class BeatmapMetadataLookupKind(Enum):
    """Fetch targetから導出するmetadata provider lookup種別を表す閉集合.

    Attributes:
        BEATMAP_ID (str): beatmap IDによるlookupを示す値.
        BEATMAPSET_ID (str): beatmapset IDによるlookupを示す値.
        CHECKSUM (str): MD5 checksumによるlookupを示す値.
    """

    BEATMAP_ID = "beatmap_id"
    BEATMAPSET_ID = "beatmapset_id"
    CHECKSUM = "checksum"


@dataclass(slots=True, frozen=True)
class BeatmapMetadataLookupTarget:
    """Fetch targetが要求するprovider非依存metadata lookupを表す.

    Attributes:
        kind (BeatmapMetadataLookupKind): lookupに使う識別子の種別.
        value (str): providerへ渡す識別子の文字列表現.
    """

    kind: BeatmapMetadataLookupKind
    value: str

    def int_value(self) -> int:
        """Lookup値を正の整数識別子として返す.

        Returns:
            int: valueを変換した正の整数.

        Raises:
            ValueError: valueが整数へ変換できないか,0以下の場合.
        """
        value = int(self.value)
        if value <= 0:
            msg = f"lookup value must be positive: {self.value}"
            raise ValueError(msg)
        return value


@dataclass(slots=True, frozen=True)
class BeatmapFetchQueuePayload:
    """Worker queueへ渡すprimitive fetch payloadを表す.

    Attributes:
        target_type (str): queueで使うfetch target typeの文字列表現.
        target_key (str): target typeに対応するlookup key.
        force_refresh (bool): cached状態にかかわらずrefreshを要求するか.
    """

    target_type: str
    target_key: str
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapFetchTarget:
    """Fetch queue encodingを隠すbeatmap metadata/file取得対象を表す.

    Attributes:
        target_type (BeatmapFetchTargetKind): metadataまたはfile fetchのtarget type.
        target_key (str): target typeに対応する非空のlookup key.
        force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

    Notes:
        target_keyの解釈はtarget_typeに依存する. file targetはmetadata lookupに使えない.
    """

    target_type: BeatmapFetchTargetKind
    target_key: str
    force_refresh: bool = field(default=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        """Target typeと非空lookup keyの不変条件を検証する.

        Returns:
            None: target_typeとtarget_keyを検証して完了する.

        Raises:
            ValueError: target_typeが未対応か,target_keyが空文字列の場合.
        """
        _ = self.kind
        if not self.target_key:
            raise ValueError("target_key must not be empty")

    @property
    def kind(self) -> BeatmapFetchTargetKind:
        """Target typeをtyped fetch target kindとして返す.

        Returns:
            BeatmapFetchTargetKind: target_typeに対応するenum member.

        Raises:
            ValueError: target_typeがBeatmapFetchTargetKindの値でない場合.
        """
        try:
            return BeatmapFetchTargetKind(self.target_type)
        except ValueError as exc:
            msg = f"unsupported beatmap fetch target type: {self.target_type}"
            raise ValueError(msg) from exc

    @property
    def is_file_fetch(self) -> bool:
        """このtargetをfile fetch workerが処理するか返す.

        Returns:
            bool: kindがFILE_BY_BEATMAP_IDの場合はTrue.

        Raises:
            ValueError: target_typeがBeatmapFetchTargetKindの値でない場合.
        """
        return self.kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID

    def metadata_lookup_target(self) -> BeatmapMetadataLookupTarget:
        """このfetch targetが表すmetadata lookupを返す.

        Returns:
            BeatmapMetadataLookupTarget: metadata providerへ渡すlookup種別と値.

        Raises:
            ValueError: target_typeが未対応か,file fetch targetをmetadata lookupへ
                変換しようとした場合.
        """
        match self.kind:
            case BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.BEATMAP_ID,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.BEATMAPSET_ID,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.METADATA_BY_CHECKSUM:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.CHECKSUM,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID:
                msg = "file fetch target cannot be used for metadata lookup"
                raise ValueError(msg)

    def file_beatmap_id(self) -> int:
        """File fetch targetが表すbeatmap IDを返す.

        Returns:
            int: target_keyを整数化したbeatmap ID.

        Raises:
            ValueError: target_typeがfile fetchでないか,target_keyを整数へ変換できない場合.
        """
        if self.kind is not BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID:
            msg = f"unsupported file fetch target type: {self.target_type}"
            raise ValueError(msg)
        return int(self.target_key)

    def queue_payload(self) -> BeatmapFetchQueuePayload:
        """Worker queueへ渡せるprimitive payloadを返す.

        Returns:
            BeatmapFetchQueuePayload: kindの文字列表現,target key,force refresh指定を持つpayload.

        Raises:
            ValueError: target_typeがBeatmapFetchTargetKindの値でない場合.
        """
        return BeatmapFetchQueuePayload(
            target_type=self.kind.value,
            target_key=self.target_key,
            force_refresh=self.force_refresh,
        )

    @classmethod
    def from_queue_payload(
        cls,
        *,
        target_type: str,
        target_key: str,
        force_refresh: bool = False,
    ) -> BeatmapFetchTarget:
        """Worker queue payloadからfetch targetを復元する.

        Args:
            target_type (str): queue payloadに格納されたtarget type.
            target_key (str): queue payloadに格納されたlookup key.
            force_refresh (bool): queue payloadに格納されたforce refresh指定.

        Returns:
            BeatmapFetchTarget: typed target typeを持つfetch target.

        Raises:
            ValueError: target_typeが未対応か,target_keyが空文字列の場合.
        """
        return cls(
            target_type=BeatmapFetchTargetKind(target_type),
            target_key=target_key,
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_beatmap_id(
        cls, beatmap_id: int, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """Beatmap IDを指定したmetadata fetch targetを作る.

        Args:
            beatmap_id (int): metadataを取得するbeatmap ID.
            force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

        Returns:
            BeatmapFetchTarget: METADATA_BY_BEATMAP_IDを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID,
            target_key=str(beatmap_id),
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_beatmapset_id(
        cls, beatmapset_id: int, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """Beatmapset IDを指定したmetadata fetch targetを作る.

        Args:
            beatmapset_id (int): metadataを取得するbeatmapset ID.
            force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

        Returns:
            BeatmapFetchTarget: METADATA_BY_BEATMAPSET_IDを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID,
            target_key=str(beatmapset_id),
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_checksum(
        cls, checksum_md5: str, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """MD5 checksumを指定したmetadata fetch targetを作る.

        Args:
            checksum_md5 (str): metadataを取得するbeatmapのMD5 checksum.
            force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

        Returns:
            BeatmapFetchTarget: METADATA_BY_CHECKSUMを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_CHECKSUM,
            target_key=checksum_md5,
            force_refresh=force_refresh,
        )

    @classmethod
    def file_by_beatmap_id(cls, beatmap_id: int) -> BeatmapFetchTarget:
        """Beatmap IDを指定したosu file fetch targetを作る.

        Args:
            beatmap_id (int): osu fileを取得するbeatmap ID.

        Returns:
            BeatmapFetchTarget: FILE_BY_BEATMAP_IDを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID,
            target_key=str(beatmap_id),
        )


@dataclass(slots=True, frozen=True)
class BeatmapFetchRecord:
    """Fetch queue上の取得試行状態を表す.

    Attributes:
        target (BeatmapFetchTarget): 試行するmetadataまたはfile取得対象.
        status (BeatmapFetchState): 現在の取得試行状態.
        attempt_count (int): これまでの取得試行回数.
        last_error (str | None): 直近失敗の診断message. 成功または未試行時はNone.
        pending_since (datetime | None): pending状態を開始した日時. pendingでない場合はNone.
        last_attempted_at (datetime | None): 最後に取得を試行した日時. 未試行時はNone.
    """

    target: BeatmapFetchTarget
    status: BeatmapFetchState
    attempt_count: int
    last_error: str | None
    pending_since: datetime | None
    last_attempted_at: datetime | None
