"""Channel read model 用 read-only query repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride


class ChannelQueryRepository(Protocol):
    """Display と compatibility workflow 用 channel read-only access を定義する.

    Notes:
        この Protocol は channel と role override の read model を返すだけである. Channel state や
        override を変更せず Command Unit of Work を開始または commit/rollback しない.
    """

    async def get_by_name(self, name: str) -> Channel | None:
        """Name に対応する Channel を返す.

        Args:
            name (str): 検索する channel name.

        Returns:
            Channel | None: 対応する Channel. 見つからない場合は `None`.
        """
        ...

    async def get_all(self) -> list[Channel]:
        """すべての public Channel を返す.

        Returns:
            list[Channel]: Public Channel の一覧. 対象がない場合は空の list.
        """
        ...

    async def get_auto_join(self) -> list[Channel]:
        """Auto-join 対象の Channel を返す.

        Returns:
            list[Channel]: Auto-join Channel の一覧. 対象がない場合は空の list.
        """
        ...

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """一つの Channel に適用する role override を返す.

        Args:
            channel_id (int): Role override を取得する Channel ID.

        Returns:
            list[ChannelRoleOverride]: Channel の role override 一覧. 対象がない場合は空の list.
        """
        ...

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """複数 Channel の role override を Channel ID ごとに返す.

        Args:
            channel_ids (list[int]): Role override を取得する Channel ID の一覧.

        Returns:
            dict[int, list[ChannelRoleOverride]]: Channel ID を key とする role override 一覧.
        """
        ...
