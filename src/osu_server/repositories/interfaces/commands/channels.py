"""Channel mutation workflow の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride


@runtime_checkable
class ChannelCommandRepository(Protocol):
    """Channel の mutation と consistency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する。各操作は同じ Unit of Work が
        所有する transaction に参加し、この repository 自身は commit または rollback を
        実行しない.
    """

    async def create(self, channel: Channel) -> Channel:
        """新しい Channel を永続化し repository-assigned identity 付きで返す.

        Args:
            channel (Channel): 永続化する未保存 Channel.

        Returns:
            Channel: Repository-assigned identity を含む永続化後の Channel.

        Raises:
            ValueError: 同じ name の Channel が既に存在する場合に送出する.
        """
        ...

    async def get_by_name(self, name: str) -> Channel | None:
        """Uniqueness と ACL check 用に name から Channel を返す.

        Args:
            name (str): 検索する Channel name.

        Returns:
            Channel | None: 一致する Channel。存在しない場合は None.
        """
        ...

    async def update(self, channel: Channel) -> Channel:
        """Channel の変更を永続化する.

        Args:
            channel (Channel): 更新内容を含む Channel.

        Returns:
            Channel: 永続化後の Channel.

        Raises:
            ValueError: 対象 Channel が存在しない場合、または変更後の name が別 Channel と
                重複する場合に送出する.
        """
        ...

    async def delete(self, channel_id: int) -> None:
        """Identifier で Channel を削除する.

        Args:
            channel_id (int): 削除する Channel ID.

        Returns:
            None: 削除が Unit of Work に反映されたことを示す.
        """
        ...

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """Channel command decision 用に role override を返す.

        Args:
            channel_id (int): Override を取得する Channel ID.

        Returns:
            list[ChannelRoleOverride]: Channel に設定された role override 群.
        """
        ...

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """Command decision 用に Channel ID ごとの role override を返す.

        Args:
            channel_ids (list[int]): Override を取得する Channel ID 群.

        Returns:
            dict[int, list[ChannelRoleOverride]]: Channel ID を key とする role override 群.
        """
        ...
