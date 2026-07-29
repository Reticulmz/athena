"""SQLAlchemyでBeatmap関連dataをread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    attachment_to_domain,
    beatmap_to_domain,
    beatmapset_to_domain,
    fetch_state_to_domain,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
    )


class SQLAlchemyBeatmapQueryRepository:
    """短命なSQLAlchemy read sessionでBeatmap関連read modelを取得する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Returns:
            None: 読み取り用session factoryを保持したrepository instanceを初期化する.

        Notes:
            初期化時にはsessionを生成せず,Beatmap metadataやfile attachmentを変更しない.
        """
        self._session_factory = session_factory

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Beatmap IDに一致するdomain Beatmapと最新file attachmentを取得する.

        Args:
            beatmap_id (int): 取得対象Beatmapの永続ID.

        Returns:
            Beatmap | None: 最新file attachmentを含むdomain Beatmap. 対象rowがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: Beatmapまたはfile attachment modelのenum値をdomain valueへ変換できない場合.

        Notes:
            file attachmentはIDの降順で最初のrowを最新として扱う.
        """
        async with self._session_factory() as session:
            model = await session.get(BeatmapModel, beatmap_id)
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session,
                beatmap_id=beatmap_id,
            )
            return beatmap_to_domain(model, attachment)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Beatmapset IDに一致するdomain Beatmapsetと所属Beatmapを取得する.

        Args:
            beatmapset_id (int): 取得対象Beatmapsetの永続ID.

        Returns:
            BeatmapSet | None: 所属Beatmapと各最新file attachmentを含むdomain Beatmapset.
            対象rowがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: Beatmapset,所属Beatmap,またはfile attachment modelのenum値をdomain
                valueへ変換できない場合.

        Notes:
            所属Beatmapの並び順はSQL queryにorder_byを指定しないため永続層の順序に依存しない.
        """
        async with self._session_factory() as session:
            model = await session.get(BeatmapSetModel, beatmapset_id)
            if not isinstance(model, BeatmapSetModel):
                return None
            beatmap_models = await self._get_beatmap_models_for_set(
                session,
                beatmapset_id=beatmapset_id,
            )
            beatmaps = [
                beatmap_to_domain(
                    beatmap_model,
                    await self._get_current_file_attachment_model(
                        session,
                        beatmap_id=beatmap_model.id,
                    ),
                )
                for beatmap_model in beatmap_models
            ]
            return beatmapset_to_domain(model, tuple(beatmaps))

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """MD5 checksumに一致するdomain Beatmapと最新file attachmentを取得する.

        Args:
            checksum_md5 (str): 完全一致で検索するBeatmap MD5 checksum.

        Returns:
            Beatmap | None: 最新file attachmentを含むdomain Beatmap. 対象rowがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: Beatmapまたはfile attachment modelのenum値をdomain valueへ変換できない場合.

        Notes:
            checksumの正規化は行わず,file attachmentはIDの降順で最新を選ぶ.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(BeatmapModel).where(BeatmapModel.checksum_md5 == checksum_md5)
                )
            ).scalar_one_or_none()
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session,
                beatmap_id=model.id,
            )
            return beatmap_to_domain(model, attachment)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Beatmapset内のoriginal filenameに一致するdomain Beatmapを取得する.

        Args:
            beatmapset_id (int): 検索対象Beatmapsetの永続ID.
            original_filename (str): file attachmentに保存された完全一致のfilename.

        Returns:
            Beatmap | None: 最新file attachmentを含むdomain Beatmap. 対象rowがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: Beatmapまたはfile attachment modelのenum値をdomain valueへ変換できない場合.

        Notes:
            複数rowが一致した場合の選択順はSQL queryにorder_byを指定しないため保証しない.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(BeatmapModel)
                    .join(
                        BeatmapFileAttachmentModel,
                        BeatmapFileAttachmentModel.beatmap_id == BeatmapModel.id,
                    )
                    .where(
                        BeatmapModel.beatmapset_id == beatmapset_id,
                        BeatmapFileAttachmentModel.original_filename == original_filename,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session,
                beatmap_id=model.id,
            )
            return beatmap_to_domain(model, attachment)

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Beatmapの最新file attachmentを取得する.

        Args:
            beatmap_id (int): attachmentを検索するBeatmapの永続ID.

        Returns:
            BeatmapFileAttachment | None: IDが最大のdomain file attachment. Rowがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: file attachment modelのsourceをBeatmapFileSourceへ変換できない場合.

        Notes:
            attachmentがないBeatmapも例外にせずNoneとして扱う.
        """
        async with self._session_factory() as session:
            model = await self._get_current_file_attachment_model(
                session,
                beatmap_id=beatmap_id,
            )
            return attachment_to_domain(model) if model is not None else None

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Beatmap fetch targetの永続化された取得状態を取得する.

        Args:
            target (BeatmapFetchTarget): metadataまたはfile取得を識別するtarget.

        Returns:
            BeatmapFetchRecord | None: targetに一致する取得状態. Rowがない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: fetch state modelのtarget typeまたはstatusをdomain enumへ変換できない場合.

        Notes:
            fetch状態を補完または更新せず,現在の永続値だけをreadする.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(BeatmapFetchStateModel).where(
                        BeatmapFetchStateModel.target_type == target.target_type.value,
                        BeatmapFetchStateModel.target_key == target.target_key,
                    )
                )
            ).scalar_one_or_none()
            return (
                fetch_state_to_domain(model) if isinstance(model, BeatmapFetchStateModel) else None
            )

    @staticmethod
    async def _get_beatmap_models_for_set(
        session: AsyncSession,
        *,
        beatmapset_id: int,
    ) -> list[BeatmapModel]:
        """開いているsessionからBeatmapset所属のmodelを取得する.

        Args:
            session (AsyncSession): 呼び出し側が開閉を所有するSQLAlchemy read session.
            beatmapset_id (int): 所属Beatmapを検索するBeatmapsetの永続ID.

        Returns:
            list[BeatmapModel]: Beatmapset IDが一致する永続model. 該当しない場合は空list.

        Raises:
            SQLAlchemyError: statementの実行またはrow取得に失敗した場合.

        Notes:
            session lifecycleは呼び出し側が所有し,結果の並び順は指定しない.
        """
        result = await session.execute(
            select(BeatmapModel).where(BeatmapModel.beatmapset_id == beatmapset_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def _get_current_file_attachment_model(
        session: AsyncSession,
        *,
        beatmap_id: int,
    ) -> BeatmapFileAttachmentModel | None:
        """開いているsessionからBeatmapの最新file attachment modelを取得する.

        Args:
            session (AsyncSession): 呼び出し側が開閉を所有するSQLAlchemy read session.
            beatmap_id (int): attachmentを検索するBeatmapの永続ID.

        Returns:
            BeatmapFileAttachmentModel | None: IDが最大のattachment model. 対象rowがない場合はNone.

        Raises:
            SQLAlchemyError: statementの実行またはrow取得に失敗した場合.

        Notes:
            session lifecycleは呼び出し側が所有し,attachment stateは変更しない.
        """
        model = (
            await session.execute(
                select(BeatmapFileAttachmentModel)
                .where(BeatmapFileAttachmentModel.beatmap_id == beatmap_id)
                .order_by(BeatmapFileAttachmentModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None
