"""SQLAlchemyでchat channelを永続化するcommand repositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelModel,
    ChannelRoleOverrideModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyChannelCommandRepository:
    """Unit of Work所有sessionでchannelとrole overrideを操作するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): channel操作に使うsession.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def create(self, channel: Channel) -> Channel:
        """名前が重複しないchannelを新規作成する.

        Args:
            channel (Channel): 新規rowへ保存するchannel属性.

        Returns:
            Channel: flushとrefresh後の永続化済みchannel.

        Raises:
            ValueError: 同じchannel nameが既に存在する場合.
            SQLAlchemyError: 検索または永続化処理に失敗した場合.

        Notes:
            このmethodはUnit of Workをcommitしない.
        """
        existing = (
            await self._session.execute(
                select(ChannelModel).where(ChannelModel.name == channel.name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            msg = f"channel name already exists: {channel.name}"
            raise ValueError(msg)

        model = ChannelModel(
            name=channel.name,
            topic=channel.topic,
            channel_type=channel.channel_type.value,
            auto_join=channel.auto_join,
            rate_limit_messages=channel.rate_limit_messages,
            rate_limit_window=channel.rate_limit_window,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _channel_to_domain(model)

    async def get_by_name(self, name: str) -> Channel | None:
        """名前で保存済みchannelを取得する.

        Args:
            name (str): 取得対象channelの完全一致name.

        Returns:
            Channel | None: 対応するchannel. 存在しない場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (
            await self._session.execute(select(ChannelModel).where(ChannelModel.name == name))
        ).scalar_one_or_none()
        return _channel_to_domain(model) if isinstance(model, ChannelModel) else None

    async def update(self, channel: Channel) -> Channel:
        """既存channelを指定属性で更新する.

        Args:
            channel (Channel): idと更新後の全属性を持つchannel.

        Returns:
            Channel: flushとrefresh後の更新済みchannel.

        Raises:
            ValueError: 指定idのchannelが存在しない場合.
            SQLAlchemyError: 検索または永続化処理に失敗した場合.

        Notes:
            名前の重複検査は行わず既存のdatabase制約に従う.
        """
        model = await self._session.get(ChannelModel, channel.id)
        if model is None:
            msg = f"channel not found: id={channel.id}"
            raise ValueError(msg)
        assert isinstance(model, ChannelModel)

        model.name = channel.name
        model.topic = channel.topic
        model.channel_type = channel.channel_type.value
        model.auto_join = channel.auto_join
        model.rate_limit_messages = channel.rate_limit_messages
        model.rate_limit_window = channel.rate_limit_window
        await self._session.flush()
        await self._session.refresh(model)
        return _channel_to_domain(model)

    async def delete(self, channel_id: int) -> None:
        """指定idのchannelが存在する場合だけ削除する.

        Args:
            channel_id (int): 削除対象channelの永続化識別子.

        Returns:
            None: 存在しないchannelも含め削除処理を完了したことを示す.

        Raises:
            SQLAlchemyError: 検索または削除のflushに失敗した場合.

        Notes:
            存在しないidは例外にせずno-opとして扱う.
        """
        model = await self._session.get(ChannelModel, channel_id)
        if model is not None:
            assert isinstance(model, ChannelModel)
            await self._session.delete(model)
            await self._session.flush()

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """1つのchannelに設定されたrole overrideを取得する.

        Args:
            channel_id (int): overrideを取得するchannelの永続化識別子.

        Returns:
            list[ChannelRoleOverride]: 取得したoverrideのlist. 未設定時は空list.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        models = (
            (
                await self._session.execute(
                    select(ChannelRoleOverrideModel).where(
                        ChannelRoleOverrideModel.channel_id == channel_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return [_override_to_domain(model) for model in models]

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """複数channelのrole overrideをchannel idごとに取得する.

        Args:
            channel_ids (list[int]): 取得対象channelの永続化識別子.

        Returns:
            dict[int, list[ChannelRoleOverride]]: 各入力idをkeyにするoverride list.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.

        Notes:
            空list入力ではSQLを実行せず空dictを返す.
        """
        if not channel_ids:
            return {}

        result: dict[int, list[ChannelRoleOverride]] = {
            channel_id: [] for channel_id in channel_ids
        }
        models = (
            (
                await self._session.execute(
                    select(ChannelRoleOverrideModel).where(
                        ChannelRoleOverrideModel.channel_id.in_(channel_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        for model in models:
            result[model.channel_id].append(_override_to_domain(model))
        return result


def _channel_to_domain(model: ChannelModel) -> Channel:
    """SQLAlchemy channel modelをchat domain modelへ変換する.

    Args:
        model (ChannelModel): 永続化層から読み出したchannel row.

    Returns:
        Channel: channel typeをdomain enumへ復元したchannel.

    Raises:
        ValueError: channel_typeが既知のchannel typeでない場合.
    """
    return Channel(
        id=model.id,
        name=model.name,
        topic=model.topic,
        channel_type=ChannelType(model.channel_type),
        auto_join=model.auto_join,
        rate_limit_messages=model.rate_limit_messages,
        rate_limit_window=model.rate_limit_window,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _override_to_domain(model: ChannelRoleOverrideModel) -> ChannelRoleOverride:
    """SQLAlchemy channel role override modelをdomain modelへ変換する.

    Args:
        model (ChannelRoleOverrideModel): 永続化層から読み出したoverride row.

    Returns:
        ChannelRoleOverride: channelとroleの権限設定を表すdomain value.
    """
    return ChannelRoleOverride(
        channel_id=model.channel_id,
        role_id=model.role_id,
        can_read=model.can_read,
        can_write=model.can_write,
    )
