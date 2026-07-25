"""In-memory channel command/query repositoryの契約を検証する."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.chat.channels import Channel, ChannelType
from osu_server.repositories.interfaces.commands.channels import ChannelCommandRepository
from osu_server.repositories.memory.commands.channels import InMemoryChannelCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


def _make_channel(
    *,
    id: int = 0,  # noqa: A002
    name: str = "#osu",
    topic: str = "General discussion",
    channel_type: ChannelType = ChannelType.PUBLIC,
    auto_join: bool = False,
    rate_limit_messages: int | None = None,
    rate_limit_window: int | None = None,
) -> Channel:
    """test用の既定値を持つChannelを作成する.

    Args:
        id (int): 作成前または保存済みchannelの識別子.
        name (str): channel名.
        topic (str): channelの表示topic.
        channel_type (ChannelType): channelの公開種別.
        auto_join (bool): 接続時に自動参加させるか.
        rate_limit_messages (int | None): rate limit window内の最大message数.
        rate_limit_window (int | None): rate limitを評価する秒数.

    Returns:
        Channel: 指定metadataと現在時刻を持つchannel.
    """
    now = datetime.now(UTC)
    return Channel(
        id=id,
        name=name,
        topic=topic,
        channel_type=channel_type,
        auto_join=auto_join,
        rate_limit_messages=rate_limit_messages,
        rate_limit_window=rate_limit_window,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def command_state() -> InMemoryCommandRepositoryState:
    """各testで共有する空のin-memory command stateを提供する.

    Returns:
        InMemoryCommandRepositoryState: channelを保存していない独立state.
    """
    return InMemoryCommandRepositoryState()


@pytest.fixture
def repo(command_state: InMemoryCommandRepositoryState) -> InMemoryChannelCommandRepository:
    """Fixture stateへ書き込むin-memory channel command repositoryを提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): test内で共有するcommand-side state.

    Returns:
        InMemoryChannelCommandRepository: channelを作成して更新し削除するrepository.
    """
    return InMemoryChannelCommandRepository(command_state)


@pytest.fixture
def query_repo(command_state: InMemoryCommandRepositoryState) -> InMemoryChannelQueryRepository:
    """Fixture stateを読み取るin-memory channel query repositoryを提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): command repositoryと共有するstate.

    Returns:
        InMemoryChannelQueryRepository: 保存済みchannelを読み取るquery repository.
    """
    return InMemoryChannelQueryRepository(InMemoryUnitOfWorkFactory(command_state))


class TestProtocolConformance:
    """In-memory command repositoryのProtocol conformanceを検証するtest group."""

    def test_is_instance_of_protocol(self, repo: InMemoryChannelCommandRepository) -> None:
        """Command repositoryがruntime Protocol instanceとして認識されることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): conformanceを検証するrepository fixture.

        Returns:
            None: runtime Protocol instance判定を検証して完了する.
        """
        assert isinstance(repo, ChannelCommandRepository)


class TestCreate:
    """Channel create操作の保存結果とidentity割当を検証するtest group."""

    async def test_returns_channel_with_generated_id(
        self, repo: InMemoryChannelCommandRepository
    ) -> None:
        """createが保存済みchannelへ自動生成IDを割り当てることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): channelを保存するrepository fixture.

        Returns:
            None: 生成IDと既定metadataを検証して完了する.
        """
        channel = _make_channel()

        created = await repo.create(channel)

        assert created.id > 0
        assert created.name == "#osu"
        assert created.topic == "General discussion"

    async def test_preserves_all_fields(self, repo: InMemoryChannelCommandRepository) -> None:
        """createがchannelの全domain fieldを保持することを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): channelを保存するrepository fixture.

        Returns:
            None: 保存後のchannel metadataが入力値と一致することを検証して完了する.
        """
        channel = _make_channel(
            name="#staff",
            topic="Staff only",
            auto_join=True,
            rate_limit_messages=5,
            rate_limit_window=10,
        )

        created = await repo.create(channel)

        assert created.name == "#staff"
        assert created.topic == "Staff only"
        assert created.channel_type == ChannelType.PUBLIC
        assert created.auto_join is True
        assert created.rate_limit_messages == 5
        assert created.rate_limit_window == 10

    async def test_auto_increment_ids(self, repo: InMemoryChannelCommandRepository) -> None:
        """連続したcreateが連番channel IDを割り当てることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): channelを連続作成するrepository fixture.

        Returns:
            None: 先行channelと後続channelのID順序を検証して完了する.
        """
        ch_a = await repo.create(_make_channel(name="#osu"))
        ch_b = await repo.create(_make_channel(name="#announce"))

        assert ch_a.id == 1
        assert ch_b.id == 2

    async def test_duplicate_name_raises(self, repo: InMemoryChannelCommandRepository) -> None:
        """既存channel名でのcreateが重複errorになることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 同名channelを保存するrepository fixture.

        Returns:
            None: 重複channel名に対するValueErrorを検証して完了する.
        """
        _ = await repo.create(_make_channel(name="#osu"))

        with pytest.raises(ValueError, match="channel name already exists"):
            _ = await repo.create(_make_channel(name="#osu"))


class TestGetByName:
    """Channel名によるquery repository lookupを検証するtest group."""

    async def test_found(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        """保存済みchannel名のlookupが対応するchannelを返すことを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): lookup前のchannelを保存するrepository fixture.
            query_repo (InMemoryChannelQueryRepository): 保存済みchannelを検索するquery fixture.

        Returns:
            None: 検索結果の存在とchannel名を検証して完了する.
        """
        _ = await repo.create(_make_channel(name="#osu"))

        result = await query_repo.get_by_name("#osu")

        assert result is not None
        assert result.name == "#osu"

    async def test_not_found_returns_none(
        self, query_repo: InMemoryChannelQueryRepository
    ) -> None:
        """未保存channel名のlookupがNoneを返すことを検証する.

        Args:
            query_repo (InMemoryChannelQueryRepository): 空stateを検索するquery fixture.

        Returns:
            None: 欠損channelに対するNone結果を検証して完了する.
        """
        result = await query_repo.get_by_name("#nonexistent")

        assert result is None


class TestGetAll:
    """公開channelだけを返すquery repository一覧取得を検証するtest group."""

    async def test_returns_public_channels(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        """公開channelが一覧queryへすべて含まれることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 公開channelを保存するrepository fixture.
            query_repo (InMemoryChannelQueryRepository): channel一覧を取得するquery fixture.

        Returns:
            None: 保存した公開channelの個数と名前集合を検証して完了する.
        """
        _ = await repo.create(_make_channel(name="#osu"))
        _ = await repo.create(_make_channel(name="#announce"))

        result = await query_repo.get_all()

        assert len(result) == 2
        names = {ch.name for ch in result}
        assert names == {"#osu", "#announce"}

    async def test_excludes_non_public_channels(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        """非公開channelが公開channel一覧queryから除外されることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 公開種別の異なるchannelを保存するfixture.
            query_repo (InMemoryChannelQueryRepository): 公開channel一覧を取得するquery fixture.

        Returns:
            None: PUBLIC channelだけが結果に残ることを検証して完了する.
        """
        _ = await repo.create(_make_channel(name="#osu", channel_type=ChannelType.PUBLIC))
        _ = await repo.create(_make_channel(name="#mp-1", channel_type=ChannelType.MULTIPLAYER))
        _ = await repo.create(_make_channel(name="#spec-1", channel_type=ChannelType.SPECTATOR))

        result = await query_repo.get_all()

        assert len(result) == 1
        assert result[0].name == "#osu"

    async def test_empty_when_no_channels(
        self, query_repo: InMemoryChannelQueryRepository
    ) -> None:
        """空stateの一覧queryが空listを返すことを検証する.

        Args:
            query_repo (InMemoryChannelQueryRepository): 保存済みchannelを持たないquery fixture.

        Returns:
            None: 結果が空listであることを検証して完了する.
        """
        result = await query_repo.get_all()

        assert result == []


class TestGetAutoJoin:
    """Auto-join channelだけを返すquery repository lookupを検証するtest group."""

    async def test_returns_auto_join_channels(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        """Auto-join設定のchannelだけが専用queryへ含まれることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): auto-join channelを保存するfixture.
            query_repo (InMemoryChannelQueryRepository): auto-join channelを取得するquery fixture.

        Returns:
            None: auto-join channelの個数と名前を検証して完了する.
        """
        _ = await repo.create(_make_channel(name="#osu", auto_join=True))
        _ = await repo.create(_make_channel(name="#staff", auto_join=False))

        result = await query_repo.get_auto_join()

        assert len(result) == 1
        assert result[0].name == "#osu"

    async def test_empty_when_none_auto_join(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        """Auto-join channelがない場合に専用queryが空listを返すことを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): auto-join無効channelを保存するfixture.
            query_repo (InMemoryChannelQueryRepository): auto-join channelを取得するquery fixture.

        Returns:
            None: 結果が空listであることを検証して完了する.
        """
        _ = await repo.create(_make_channel(name="#osu", auto_join=False))

        result = await query_repo.get_auto_join()

        assert result == []


class TestUpdate:
    """既存channelのupdate操作とname index整合性を検証するtest group."""

    async def test_updates_fields(self, repo: InMemoryChannelCommandRepository) -> None:
        """Updateが既存channelの変更可能fieldを置き換えることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): channelを作成して更新するrepository fixture.

        Returns:
            None: topicとauto-join設定の更新結果を検証して完了する.
        """
        created = await repo.create(_make_channel(name="#osu", topic="Old topic"))
        modified = Channel(
            id=created.id,
            name=created.name,
            topic="New topic",
            channel_type=created.channel_type,
            auto_join=True,
            rate_limit_messages=created.rate_limit_messages,
            rate_limit_window=created.rate_limit_window,
            created_at=created.created_at,
            updated_at=created.updated_at,
        )

        updated = await repo.update(modified)

        assert updated.topic == "New topic"
        assert updated.auto_join is True

    async def test_updates_name_with_index(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        """Update後のchannel名がquery indexへ反映されることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): channel名を更新するrepository fixture.
            query_repo (InMemoryChannelQueryRepository): 更新前後のname indexを検索するfixture.

        Returns:
            None: 新しいnameが検索でき古いnameが検索できないことを検証して完了する.
        """
        created = await repo.create(_make_channel(name="#osu"))
        modified = Channel(
            id=created.id,
            name="#general",
            topic=created.topic,
            channel_type=created.channel_type,
            auto_join=created.auto_join,
            rate_limit_messages=created.rate_limit_messages,
            rate_limit_window=created.rate_limit_window,
            created_at=created.created_at,
            updated_at=created.updated_at,
        )

        _ = await repo.update(modified)

        assert await query_repo.get_by_name("#general") is not None
        assert await query_repo.get_by_name("#osu") is None

    async def test_name_conflict_raises(self, repo: InMemoryChannelCommandRepository) -> None:
        """既存nameへのupdateが重複errorになることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 衝突する2 channelを保持するrepository fixture.

        Returns:
            None: name index衝突に対するValueErrorを検証して完了する.
        """
        created = await repo.create(_make_channel(name="#osu"))
        _ = await repo.create(_make_channel(name="#announce"))

        modified = Channel(
            id=created.id,
            name="#announce",
            topic=created.topic,
            channel_type=created.channel_type,
            auto_join=created.auto_join,
            rate_limit_messages=created.rate_limit_messages,
            rate_limit_window=created.rate_limit_window,
            created_at=created.created_at,
            updated_at=created.updated_at,
        )

        with pytest.raises(ValueError, match="channel name already exists"):
            _ = await repo.update(modified)

    async def test_nonexistent_raises(self, repo: InMemoryChannelCommandRepository) -> None:
        """未保存channelのupdateがnot found errorになることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 未保存channelを更新するrepository fixture.

        Returns:
            None: 未存在IDに対するValueErrorを検証して完了する.
        """
        channel = _make_channel(name="#ghost")
        channel = Channel(
            id=9999,
            name=channel.name,
            topic=channel.topic,
            channel_type=channel.channel_type,
            auto_join=channel.auto_join,
            rate_limit_messages=channel.rate_limit_messages,
            rate_limit_window=channel.rate_limit_window,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
        )

        with pytest.raises(ValueError, match="channel not found"):
            _ = await repo.update(channel)


class TestDelete:
    """Channel delete操作とname index解放を検証するtest group."""

    async def test_removes_channel(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        """Delete後のchannelがquery lookupから消えることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 削除対象channelを保存するrepository fixture.
            query_repo (InMemoryChannelQueryRepository): 削除後のchannelを検索するquery fixture.

        Returns:
            None: 削除済みchannel名のlookupがNoneになることを検証して完了する.
        """
        created = await repo.create(_make_channel(name="#osu"))

        await repo.delete(created.id)

        assert await query_repo.get_by_name("#osu") is None

    async def test_removes_name_index(self, repo: InMemoryChannelCommandRepository) -> None:
        """Deleteがchannel名を再利用可能にすることを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 同名channelを再作成するfixture.

        Returns:
            None: 再作成したchannelが別IDを受け取ることを検証して完了する.
        """
        created = await repo.create(_make_channel(name="#osu"))

        await repo.delete(created.id)

        # Name should be available for reuse
        recreated = await repo.create(_make_channel(name="#osu"))
        assert recreated.id != created.id

    async def test_nonexistent_is_noop(self, repo: InMemoryChannelCommandRepository) -> None:
        """未保存channelのdeleteが例外を送出せず完了することを検証する.

        Args:
            repo (InMemoryChannelCommandRepository): 存在しないIDを削除するrepository fixture.

        Returns:
            None: delete操作が例外なしで完了することを検証して完了する.
        """
        await repo.delete(9999)  # Should not raise
