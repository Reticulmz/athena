"""SQLAlchemyからchannelとrole overrideをread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from sqlalchemy import select

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelModel,
    ChannelRoleOverrideModel,
)
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    channel_override_to_domain,
    channel_to_domain,
)


class SQLAlchemyChannelQueryRepository:
    """短命なSQLAlchemy read sessionでchannel read modelを取得する.

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
            初期化時にはsessionを生成せず、channel stateは変更しない.
        """
        self._session_factory = session_factory

    async def get_by_name(self, name: str) -> Channel | None:
        """channel名に一致するdomain Channelを取得する.

        Args:
            name (str): 完全一致で検索するchannel名.

        Returns:
            Channel | None: domain Channel. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: model.channel_typeをChannelTypeへ変換できない場合.

        Notes:
            channel名の正規化は行わない.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(select(ChannelModel).where(ChannelModel.name == name))
            ).scalar_one_or_none()
            return channel_to_domain(model) if isinstance(model, ChannelModel) else None

    async def get_all(self) -> list[Channel]:
        """PUBLIC channelだけをdomain Channelのlistとして取得する.

        Returns:
            list[Channel]: channel typeがPUBLICのdomain Channel. 該当しない場合は空list.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: model.channel_typeをChannelTypeへ変換できない場合.

        Notes:
            private channelやmultiplayer channelは含めない.
        """
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelModel).where(
                            ChannelModel.channel_type == ChannelType.PUBLIC.value
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [channel_to_domain(model) for model in models]

    async def get_auto_join(self) -> list[Channel]:
        """auto_joinが有効なdomain Channelを取得する.

        Returns:
            list[Channel]: auto_joinがTrueのdomain Channel. 該当しない場合は空list.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: model.channel_typeをChannelTypeへ変換できない場合.

        Notes:
            channel typeではなく永続されたauto_join flagだけで絞り込む.
        """
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelModel).where(ChannelModel.auto_join.is_(True))
                    )
                )
                .scalars()
                .all()
            )
            return [channel_to_domain(model) for model in models]

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """1つのchannelに設定されたrole overrideを取得する.

        Args:
            channel_id (int): overrideを検索するchannelの永続ID.

        Returns:
            list[ChannelRoleOverride]: channelに属するdomain role override. 該当しない場合は空list.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            channel自体が存在するかは検証しない.
        """
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelRoleOverrideModel).where(
                            ChannelRoleOverrideModel.channel_id == channel_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [channel_override_to_domain(model) for model in models]

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """複数channelのrole overrideをchannel IDごとに取得する.

        Args:
            channel_ids (list[int]): 検索対象channelの永続ID.

        Returns:
            dict[int, list[ChannelRoleOverride]]: 入力に含まれるchannel IDをkeyとするoverride list.
            空入力では空dictを返す.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            空入力ではsessionを開かず、重複したIDは1つのdict keyとして扱う.
        """
        if not channel_ids:
            return {}

        result: dict[int, list[ChannelRoleOverride]] = {
            channel_id: [] for channel_id in channel_ids
        }
        async with self._session_factory() as session:
            models = (
                (
                    await session.execute(
                        select(ChannelRoleOverrideModel).where(
                            ChannelRoleOverrideModel.channel_id.in_(channel_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for model in models:
                result[model.channel_id].append(channel_override_to_domain(model))
        return result
