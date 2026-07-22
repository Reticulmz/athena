"""Committed in-memory state から Channel を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.chat.channels import ChannelType

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryChannelQueryRepository:
    """Committed in-memory state を読む read-only Channel repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, Channel と override state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.

        Returns:
            None: factory を保持する repository を構築する.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_name(self, name: str) -> Channel | None:
        """完全一致する name の Channel を取得する.

        Args:
            name (str): channel_id_by_name 索引で検索する Channel name.

        Returns:
            Channel | None: 索引先の Channel. name または Channel がなければ None.

        Notes:
            name の正規化や大文字小文字の変換は行わない.
        """
        state = self._factory.snapshot()
        channel_id = state.channel_id_by_name.get(name)
        if channel_id is None:
            return None
        return state.channels_by_id.get(channel_id)

    async def get_all(self) -> list[Channel]:
        """Public Channel をすべて取得する.

        Returns:
            list[Channel]: snapshot の channels_by_id 内で ChannelType.PUBLIC の Channel.
        """
        state = self._factory.snapshot()
        return [
            channel
            for channel in state.channels_by_id.values()
            if channel.channel_type is ChannelType.PUBLIC
        ]

    async def get_auto_join(self) -> list[Channel]:
        """auto_join が有効な Channel をすべて取得する.

        Returns:
            list[Channel]: snapshot 内で auto_join が True の Channel.
        """
        state = self._factory.snapshot()
        return [channel for channel in state.channels_by_id.values() if channel.auto_join]

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """一つの Channel に設定された Role override を取得する.

        Args:
            channel_id (int): override を取得する Channel の ID.

        Returns:
            list[ChannelRoleOverride]: snapshot 内の override を格納した新しい list. 記録がなければ
            空の list.
        """
        state = self._factory.snapshot()
        return list(state.channel_overrides_by_channel_id.get(channel_id, []))

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """複数 Channel の Role override を ID ごとに取得する.

        Args:
            channel_ids (list[int]): override を取得する Channel ID 群.

        Returns:
            dict[int, list[ChannelRoleOverride]]: 入力に含まれる各一意 ID と新しい override list の
            mapping. 記録がない ID の value は空の list.
        """
        state = self._factory.snapshot()
        return {
            channel_id: list(state.channel_overrides_by_channel_id.get(channel_id, []))
            for channel_id in channel_ids
        }
