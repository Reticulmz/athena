"""SQLAlchemyからchannelとprivate messageの履歴をread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from osu_server.repositories.interfaces.queries import ChatHistoryMessage
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory


class SQLAlchemyChatHistoryQueryRepository:
    """短命なSQLAlchemy read sessionでdisplay用chat historyを取得する.

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
            初期化時にはsessionを生成せず,message stateは変更しない.
        """
        self._session_factory = session_factory

    async def list_channel_messages(
        self,
        channel_name: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """channel名に属するmessageを新しい順に取得する.

        Args:
            channel_name (str): messageを検索するchannelの完全一致名.
            limit (int): SQL queryへ渡す最大取得件数.
            before_message_id (int | None): 指定時はこのIDより小さいmessageだけを取得するcursor.

        Returns:
            list[ChatHistoryMessage]: 新しい順のdisplay用message. 該当しない場合は空list.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            limitの妥当性は呼び出し側が保証し,repositoryは値を変更しない.
        """
        async with self._session_factory() as session:
            stmt = (
                select(ChannelMessageModel)
                .join(ChannelModel, ChannelModel.id == ChannelMessageModel.channel_id)
                .where(ChannelModel.name == channel_name)
                .order_by(ChannelMessageModel.created_at.desc(), ChannelMessageModel.id.desc())
                .limit(limit)
            )
            if before_message_id is not None:
                stmt = stmt.where(ChannelMessageModel.id < before_message_id)
            models = (await session.execute(stmt)).scalars().all()
            return [_channel_message_to_read_model(model) for model in models]

    async def list_private_messages(
        self,
        user_id: int,
        peer_user_id: int,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """2つのUser IDに関連するprivate messageを新しい順に取得する.

        Args:
            user_id (int): 表示対象のUser ID.
            peer_user_id (int): 相手として検索に含めるUser ID.
            limit (int): SQL queryへ渡す最大取得件数.
            before_message_id (int | None): 指定時はこのIDより小さいmessageだけを取得するcursor.

        Returns:
            list[ChatHistoryMessage]: 新しい順のdisplay用message. 該当しない場合は空list.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.

        Notes:
            repositoryはmessageの送受信stateを変更せず,limitの妥当性は呼び出し側が保証する.
        """
        async with self._session_factory() as session:
            stmt = (
                select(PrivateMessageModel)
                .where(
                    or_(
                        PrivateMessageModel.sender_id == user_id,
                        PrivateMessageModel.sender_id == peer_user_id,
                    ),
                    or_(
                        PrivateMessageModel.target_user_id == user_id,
                        PrivateMessageModel.target_user_id == peer_user_id,
                    ),
                )
                .order_by(PrivateMessageModel.created_at.desc(), PrivateMessageModel.id.desc())
                .limit(limit)
            )
            if before_message_id is not None:
                stmt = stmt.where(PrivateMessageModel.id < before_message_id)
            models = (await session.execute(stmt)).scalars().all()
            return [_private_message_to_read_model(model) for model in models]


def _channel_message_to_read_model(model: ChannelMessageModel) -> ChatHistoryMessage:
    """Channel message modelをdisplay用read modelへ変換する.

    Args:
        model (ChannelMessageModel): 永続化されたchannel message model.

    Returns:
        ChatHistoryMessage: ID,sender,content,created_atを転記したread model.

    Notes:
        channel IDなどdisplay contractに不要なfieldは返さない.
    """
    return ChatHistoryMessage(
        id=model.id,
        sender_id=model.sender_id,
        content=model.content,
        created_at=model.created_at,
    )


def _private_message_to_read_model(model: PrivateMessageModel) -> ChatHistoryMessage:
    """Private message modelをdisplay用read modelへ変換する.

    Args:
        model (PrivateMessageModel): 永続化されたprivate message model.

    Returns:
        ChatHistoryMessage: ID,sender,content,created_atを転記したread model.

    Notes:
        target User IDなどdisplay contractに不要なfieldは返さない.
    """
    return ChatHistoryMessage(
        id=model.id,
        sender_id=model.sender_id,
        content=model.content,
        created_at=model.created_at,
    )
