"""In-memory command 側 channel repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryChannelCommandRepository:
    """Channel primary record, name index, role override を command 用に管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, channel: Channel) -> Channel:
        """一意な name を持つ channel を作成し repository ID を割り当てる.

        Args:
            channel (Channel): 作成する channel. 入力 ID は保存時に置き換える.

        Returns:
            Channel: next_channel_id を割り当てて保存した channel.

        Raises:
            ValueError: channel.name が name index にすでに存在する場合.

        Notes:
            成功時は next_channel_id, 主記録, name index を更新する.
        """
        if channel.name in self._state.channel_id_by_name:
            msg = f"channel name already exists: {channel.name}"
            raise ValueError(msg)

        created = replace(channel, id=self._state.next_channel_id)
        self._state.next_channel_id += 1
        self._state.channels_by_id[created.id] = created
        self._state.channel_id_by_name[created.name] = created.id
        return created

    async def get_by_name(self, name: str) -> Channel | None:
        """Channel name から保存済み channel を返す.

        Args:
            name (str): 検索する完全一致 channel name.

        Returns:
            Channel | None: index と主記録が存在する channel. 未登録又は不整合時は None.
        """
        channel_id = self._state.channel_id_by_name.get(name)
        if channel_id is None:
            return None
        return self._state.channels_by_id.get(channel_id)

    async def update(self, channel: Channel) -> Channel:
        """既存 channel を更新し name 変更時は一意 index も更新する.

        Args:
            channel (Channel): 保存する channel. id は既存主記録を参照する必要がある.

        Returns:
            Channel: state に保存した引数 channel.

        Raises:
            ValueError: channel.id が未登録, 又は変更後の name が別 channel に使用されている場合.

        Notes:
            name が変わる場合は古い name index を削除してから新しい index を保存する.
        """
        existing = self._state.channels_by_id.get(channel.id)
        if existing is None:
            msg = f"channel not found: id={channel.id}"
            raise ValueError(msg)

        if existing.name != channel.name:
            if channel.name in self._state.channel_id_by_name:
                msg = f"channel name already exists: {channel.name}"
                raise ValueError(msg)
            _ = self._state.channel_id_by_name.pop(existing.name, None)
            self._state.channel_id_by_name[channel.name] = channel.id

        self._state.channels_by_id[channel.id] = channel
        return channel

    async def delete(self, channel_id: int) -> None:
        """Channel と関連する name index, role overrides を削除する.

        Args:
            channel_id (int): 削除する channel の識別子.

        Returns:
            None: channel が存在した場合は関連 state を削除したことを示す.

        Notes:
            channel_id が未登録の場合は state を変更せず例外も送出しない.
        """
        channel = self._state.channels_by_id.pop(channel_id, None)
        if channel is None:
            return
        _ = self._state.channel_id_by_name.pop(channel.name, None)
        _ = self._state.channel_overrides_by_channel_id.pop(channel_id, None)

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """一つの channel に保存した role overrides の shallow copy を返す.

        Args:
            channel_id (int): overrides を検索する channel の識別子.

        Returns:
            list[ChannelRoleOverride]: 保存順の新しい list. 未登録なら空 list.
        """
        return list(self._state.channel_overrides_by_channel_id.get(channel_id, []))

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """複数 channel の role overrides を channel ID ごとに shallow copy して返す.

        Args:
            channel_ids (list[int]): 取得対象の channel IDs. 重複は結果で一つの key に集約される.

        Returns:
            dict[int, list[ChannelRoleOverride]]:
                各入力 channel ID に対応する保存順 list. 未登録は空 list.
        """
        return {
            channel_id: list(self._state.channel_overrides_by_channel_id.get(channel_id, []))
            for channel_id in channel_ids
        }

    def seed_override(self, override: ChannelRoleOverride) -> None:
        """Command-side ACL check 用の channel role override を state に追加する.

        Args:
            override (ChannelRoleOverride): 追加する channel role override.

        Returns:
            None: override を channel ID ごとの保存順 list に追加したことを示す.

        Notes:
            channel 主記録の存在及び override の重複は検証しない.
        """
        self._state.channel_overrides_by_channel_id.setdefault(override.channel_id, []).append(
            override
        )
