"""Beatmap metadata/file providerの失敗を正規化するerror modelを定義するmodule."""

from __future__ import annotations

from enum import StrEnum


class BeatmapSourceErrorCategory(StrEnum):
    """Beatmap metadata/file sourceの失敗分類を表す閉集合.

    Attributes:
        CONFIGURATION (str): source設定が利用できないことを示す値.
        UNAUTHORIZED (str): sourceが認証を拒否したことを示す値.
        RATE_LIMITED (str): sourceのrate limitに達したことを示す値.
        TIMEOUT (str): source応答がtimeoutしたことを示す値.
        TEMPORARY_UNAVAILABLE (str): sourceが一時的に利用不能なことを示す値.
        NOT_FOUND (str): lookup対象が存在しないことを示す値.
        INVALID_RESPONSE (str): source responseを解釈できないことを示す値.
    """

    CONFIGURATION = "configuration"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TEMPORARY_UNAVAILABLE = "temporary_unavailable"
    NOT_FOUND = "not_found"
    INVALID_RESPONSE = "invalid_response"


class BeatmapSourceError(RuntimeError):
    """Beatmap metadata/file source由来の失敗を分類付きで表すRuntimeError.

    Attributes:
        category (BeatmapSourceErrorCategory): 再試行判断に使う正規化済み失敗分類.
        source (str): 失敗したmetadata/file sourceの識別子.
        lookup_key (str): sourceへ渡したlookupまたはfile取得対象の識別子.
        original_error (Exception | None): 診断用に保持する元exception. 存在しない場合はNone.
    """

    category: BeatmapSourceErrorCategory
    source: str
    lookup_key: str
    original_error: Exception | None

    def __init__(
        self,
        *,
        category: BeatmapSourceErrorCategory,
        source: str,
        lookup_key: str,
        message: str,
        original_error: Exception | None = None,
    ) -> None:
        """分類と診断情報を持つsource errorを初期化する.

        Args:
            category (BeatmapSourceErrorCategory): 発生した失敗の正規化済み分類.
            source (str): 失敗したmetadata/file sourceの識別子.
            lookup_key (str): sourceへ要求したlookupまたはfile取得対象の識別子.
            message (str): error messageとしてRuntimeErrorへ渡す説明.
            original_error (Exception | None): 原因となったexception. 原因がない場合はNone.
        """
        self.category = category
        self.source = source
        self.lookup_key = lookup_key
        self.original_error = original_error
        super().__init__(message)

    def is_permanent(self) -> bool:
        """再試行不要な永続的失敗かを返す.

        Returns:
            bool: categoryがNOT_FOUNDまたはUNAUTHORIZEDの場合はTrue.
        """
        return self.category in {
            BeatmapSourceErrorCategory.NOT_FOUND,
            BeatmapSourceErrorCategory.UNAUTHORIZED,
        }
