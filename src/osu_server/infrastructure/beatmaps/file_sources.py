"""優先順位と失敗分類に従って.osuファイルを取得するproviderを実装する."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.beatmaps import (
    BeatmapFileSource,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    OsuFileFetchResult,
)

if TYPE_CHECKING:
    from osu_server.infrastructure.http.interfaces import BeatmapHttpClient

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class _FoundError(Exception):
    """source取得成功を内部の例外制御フローで通知する.

    Attributes:
        result (OsuFileFetchResult): 成功したsourceから取得したファイル結果.
    """

    result: OsuFileFetchResult

    def __init__(self, result: OsuFileFetchResult) -> None:
        """成功結果を例外インスタンスへ保持する.

        Args:
            result (OsuFileFetchResult): source取得が成功したファイル結果.
        """
        super().__init__()
        self.result = result


@dataclass(slots=True)
class BeatmapFileProviderService:
    """.osuファイルを公式current、legacy、community mirrorの順で取得する.

    Attributes:
        http_client (BeatmapHttpClient): ファイルrequestを実行してsource errorを正規化する
            HTTP adapter.
        osu_current_url_template (str): 現行公式sourceの ``{beatmap_id}`` 付きURL template.
        osu_legacy_url_template (str): legacy公式sourceの ``{beatmap_id}`` 付きURL template.
        mirror_url_templates (list[str]): 順番に試すcommunity mirrorの
            ``{beatmap_id}`` 付きURL template.

    Notes:
        一時的な失敗は次のsourceへフォールバックする.
        404または401などの永続的な失敗は直ちに伝播する.
    """

    http_client: BeatmapHttpClient
    osu_current_url_template: str = "https://osu.ppy.sh/osu/{beatmap_id}"
    osu_legacy_url_template: str = "https://old.ppy.sh/osu/{beatmap_id}"
    mirror_url_templates: list[str] = field(default_factory=list)

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
        """指定ビートマップの.osuファイルを優先順位付きで取得する.

        Args:
            beatmap_id (int): 取得対象のビートマップID.

        Returns:
            OsuFileFetchResult: 取得したファイル本体、source、元filenameを持つ結果.

        Raises:
            BeatmapSourceError: 直接sourceの永続的失敗、または全sourceの一時的失敗で
                取得できない場合.

        Notes:
            現行公式source、legacy公式source、community mirrorの順で試す.
            mirrorは直接sourceの一時的失敗後だけ使う.
        """
        lookup_key = f"beatmap_id={beatmap_id}"

        # Phase 1: try direct sources
        try:
            await self._try_direct_sources(beatmap_id, lookup_key)
        except _FoundError as found:
            return found.result
        except BeatmapSourceError as direct_error:
            if direct_error.is_permanent():
                raise
            # temporary: fall through to mirrors

        # Phase 2: try community mirrors
        try:
            await self._try_mirror_sources(beatmap_id, lookup_key)
        except _FoundError as found:
            logger.info(
                "beatmap_mirror_fallback_used",
                source_type="file",
                beatmap_id=beatmap_id,
                source=found.result.source.value,
            )
            return found.result
        except BeatmapSourceError:
            raise

        raise BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
            source="composite",
            lookup_key=lookup_key,
            message=f"All .osu file sources exhausted for beatmap_id={beatmap_id}",
        )

    async def _try_fetch(
        self,
        *,
        url_template: str,
        beatmap_id: int,
        source: BeatmapFileSource,
        source_label: str,
        lookup_key: str,
    ) -> OsuFileFetchResult:
        """単一source URLから.osuファイルを取得してdomain結果へ変換する.

        Args:
            url_template (str): ``beatmap_id`` を埋め込むsource URL template.
            beatmap_id (int): 取得対象のビートマップID.
            source (BeatmapFileSource): 成功結果へ記録するファイルsource種別.
            source_label (str): HTTP adapterのerrorとlogへ渡すsource名.
            lookup_key (str): HTTP adapterのerrorとlogへ渡す検索値.

        Returns:
            OsuFileFetchResult: HTTP adapterが返した本体とfilenameを含むファイル結果.

        Raises:
            BeatmapSourceError: HTTP adapterがrequest失敗または不正responseを正規化した場合.
        """
        url = url_template.format(beatmap_id=beatmap_id)
        result = await self.http_client.fetch(url, source=source_label, lookup_key=lookup_key)
        return OsuFileFetchResult(
            beatmap_id=beatmap_id,
            body=result.content,
            source=source,
            original_filename=result.filename,
        )

    async def _try_direct_sources(self, beatmap_id: int, lookup_key: str) -> None:
        """現行公式sourceとlegacy公式sourceを順に試す.

        Args:
            beatmap_id (int): 取得対象のビートマップID.
            lookup_key (str): source errorとlogへ渡す検索値.

        Returns:
            None: 成功時は ``_FoundError`` を送出するため、正常復帰はしない.

        Raises:
            _FoundError: いずれかの直接sourceがファイルを取得した場合.
            BeatmapSourceError: 永続的失敗を直ちに検出した場合、または両直接sourceが一時的に
                失敗した場合.
        """
        last_error: BeatmapSourceError | None = None

        for url_template, source, label in (
            (self.osu_current_url_template, BeatmapFileSource.OSU_CURRENT, "osu_current"),
            (self.osu_legacy_url_template, BeatmapFileSource.OSU_LEGACY, "osu_legacy"),
        ):
            try:
                result = await self._try_fetch(
                    url_template=url_template,
                    beatmap_id=beatmap_id,
                    source=source,
                    source_label=label,
                    lookup_key=lookup_key,
                )
                raise _FoundError(result)
            except BeatmapSourceError as exc:
                last_error = exc
                if exc.is_permanent():
                    raise

        assert last_error is not None
        raise last_error

    async def _try_mirror_sources(self, beatmap_id: int, lookup_key: str) -> None:
        """設定順にcommunity mirror sourceを試す.

        Args:
            beatmap_id (int): 取得対象のビートマップID.
            lookup_key (str): source errorとlogへ渡す検索値.

        Returns:
            None: mirror URLが未設定の場合に、取得結果なしで復帰する.

        Raises:
            _FoundError: いずれかのmirror sourceがファイルを取得した場合.
            BeatmapSourceError: mirror sourceが永続的に失敗した場合、または全mirrorが一時的に
                失敗した場合.
        """
        last_error: BeatmapSourceError | None = None
        for idx, url_template in enumerate(self.mirror_url_templates):
            label = f"community_mirror[{idx}]"
            try:
                result = await self._try_fetch(
                    url_template=url_template,
                    beatmap_id=beatmap_id,
                    source=BeatmapFileSource.COMMUNITY_MIRROR,
                    source_label=label,
                    lookup_key=lookup_key,
                )
                raise _FoundError(result)
            except BeatmapSourceError as exc:
                last_error = exc
                if exc.is_permanent():
                    raise

        if last_error is not None:
            raise last_error
