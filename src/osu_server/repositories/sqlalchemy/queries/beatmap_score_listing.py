"""stable getscores向けBeatmap lookupをSQLAlchemy query repositoryへ委譲するadapterを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.repositories.sqlalchemy.queries.beatmaps import SQLAlchemyBeatmapQueryRepository

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapSet,
    )
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory


class SQLAlchemyBeatmapScoreListingQueryRepository:
    """stable getscoresのBeatmap lookupをread-only Beatmap repositoryへ委譲する.

    Attributes:
        _beatmaps (SQLAlchemyBeatmapQueryRepository): 共通Beatmap read operationを提供するdelegate.
    """

    _beatmaps: SQLAlchemyBeatmapQueryRepository

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """Beatmap query repository delegateを作成する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): delegate用のread session factory.

        Returns:
            None: Beatmap query repository delegateを構築して保持する.

        Notes:
            初期化時にはsessionを生成せず、delegate以外の永続stateを保持しない.
        """
        self._beatmaps = SQLAlchemyBeatmapQueryRepository(session_factory)

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """MD5 checksumでstable getscores対象Beatmapを検索する.

        Args:
            checksum_md5 (str): 完全一致で検索するBeatmap MD5 checksum.

        Returns:
            Beatmap | None: 対象Beatmap. 見つからない場合はNone.

        Raises:
            SQLAlchemyError: delegateのsession readまたはrow取得に失敗した場合.
            ValueError: delegateがBeatmapまたはfile attachment modelのenum値をdomain valueへ変換
                できない場合.

        Notes:
            lookup semanticsはSQLAlchemyBeatmapQueryRepositoryへ完全に委譲する.
        """
        return await self._beatmaps.get_beatmap_by_checksum(checksum_md5)

    async def find_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Beatmapset内のoriginal filenameでstable getscores対象Beatmapを検索する.

        Args:
            beatmapset_id (int): 検索対象Beatmapsetの永続ID.
            original_filename (str): attachmentに保存されたoriginal filename.

        Returns:
            Beatmap | None: 対象Beatmap. 見つからない場合はNone.

        Raises:
            SQLAlchemyError: delegateのsession readまたはrow取得に失敗した場合.
            ValueError: delegateがBeatmapまたはfile attachment modelのenum値をdomain valueへ変換
                できない場合.

        Notes:
            lookup semanticsはSQLAlchemyBeatmapQueryRepositoryへ完全に委譲する.
        """
        return await self._beatmaps.get_beatmap_by_filename_in_beatmapset(
            beatmapset_id,
            original_filename,
        )

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Stable getscores対象Beatmapsetを取得する.

        Args:
            beatmapset_id (int): 取得対象Beatmapsetの永続ID.

        Returns:
            BeatmapSet | None: Beatmapを含むdomain Beatmapset. 見つからない場合はNone.

        Raises:
            SQLAlchemyError: delegateのsession readまたはrow取得に失敗した場合.
            ValueError: delegateがBeatmapset、Beatmap、またはfile attachment modelのenum値をdomain
                valueへ変換できない場合.

        Notes:
            lookup semanticsはSQLAlchemyBeatmapQueryRepositoryへ完全に委譲する.
        """
        return await self._beatmaps.get_beatmapset(beatmapset_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Beatmap fetch targetの現在の取得状態を返す.

        Args:
            target (BeatmapFetchTarget): metadataまたはfile取得を識別するtarget.

        Returns:
            BeatmapFetchRecord | None: 永続化された取得状態. 対象rowがない場合はNone.

        Raises:
            SQLAlchemyError: delegateのsession readまたはrow取得に失敗した場合.
            ValueError: delegateがfetch state modelのtarget typeまたはstatusをdomain enumへ変換
                できない場合.

        Notes:
            lookup semanticsはSQLAlchemyBeatmapQueryRepositoryへ完全に委譲する.
        """
        return await self._beatmaps.get_fetch_state(target)
