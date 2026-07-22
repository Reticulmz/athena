"""In-memory command Unit of Work と committed state factory を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from osu_server.repositories.memory.commands import (
    InMemoryBeatmapCommandRepository,
    InMemoryBeatmapLeaderboardCommandRepository,
    InMemoryBeatmapPerformanceBestCommandRepository,
    InMemoryBlobCommandRepository,
    InMemoryChannelCommandRepository,
    InMemoryChatCommandRepository,
    InMemoryCommandRepositoryState,
    InMemoryCurrentUserStatsCommandRepository,
    InMemoryFriendRelationshipCommandRepository,
    InMemoryPersonalBestCommandRepository,
    InMemoryReplayCommandRepository,
    InMemoryRoleCommandRepository,
    InMemoryScoreCommandRepository,
    InMemoryScorePerformanceCommandRepository,
    InMemoryScoreSubmissionCommandRepository,
    InMemoryUserCommandRepository,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping, MutableSet
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from osu_server.domain.identity.roles import Role
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


def _replace_mapping[K, V](
    current: MutableMapping[K, V],
    value: MutableMapping[K, V],
) -> None:
    """既存 mapping の内容を別 mapping の内容で置き換える.

    Args:
        current (MutableMapping[K, V]): clear と update を行う変更対象の mapping.
        value (MutableMapping[K, V]): current へ複製する source mapping.

    Returns:
        None: current を value と同じ key/value 内容にする.

    Notes:
        value 自体は変更しない. current の container identity は維持する.
    """
    current.clear()
    current.update(value)


def _replace_set[T](current: MutableSet[T], value: MutableSet[T]) -> None:
    """既存 set の内容を別 set の内容で置き換える.

    Args:
        current (MutableSet[T]): clear と add を行う変更対象の set.
        value (MutableSet[T]): current へ複製する source set.

    Returns:
        None: current を value と同じ item 内容にする.

    Notes:
        value 自体は変更しない. current の container identity は維持する.
    """
    current.clear()
    for item in value:
        current.add(item)


class InMemoryUnitOfWorkFactory:
    """隔離された in-memory command UoW scope を開く factory.

    Attributes:
        _state (InMemoryCommandRepositoryState): query と commit の基準になる committed state.

    Notes:
        各 UoW は _state の clone を操作し, commit 時だけ factory の committed state に反映する.
    """

    def __init__(self, state: InMemoryCommandRepositoryState | None = None) -> None:
        """Committed state を指定して factory を初期化する.

        Args:
            state (InMemoryCommandRepositoryState | None): 初期 committed state. None の場合は空の
                state を作成する.

        Returns:
            None: state を保持する factory を構築する.
        """
        self._state: InMemoryCommandRepositoryState = state or InMemoryCommandRepositoryState()

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        """新しい隔離 UoW を非同期 context manager として返す.

        Returns:
            AbstractAsyncContextManager[UnitOfWork]: factory の snapshot から始まる UoW.

        Notes:
            この呼び出し時点では committed state を変更しない. 反映には返した UoW の commit が
            必要である.
        """
        return cast("AbstractAsyncContextManager[UnitOfWork]", InMemoryUnitOfWork(self))

    def snapshot(self) -> InMemoryCommandRepositoryState:
        """現在の committed state の clone を返す.

        Returns:
            InMemoryCommandRepositoryState: factory の committed state を clone した値.

        Notes:
            返した state への変更は commit_state が呼ばれるまで factory の state に反映されない.
        """
        return self._state.clone()

    def commit_state(self, state: InMemoryCommandRepositoryState) -> None:
        """UoW state を committed state に field ごとに反映する.

        Args:
            state (InMemoryCommandRepositoryState): commit する UoW の作業 state.

        Returns:
            None: factory が保持する committed state の内容を置き換える.

        Notes:
            入力 state を先に clone してから, 各 mapping/set の container identity を維持したまま
            内容と採番 counter を更新する. 入力 state は変更しない.
        """
        committed = state.clone()
        _replace_mapping(self._state.users_by_id, committed.users_by_id)
        _replace_mapping(
            self._state.user_id_by_safe_username,
            committed.user_id_by_safe_username,
        )
        _replace_mapping(self._state.user_id_by_email, committed.user_id_by_email)
        _replace_set(self._state.disallowed_usernames, committed.disallowed_usernames)
        self._state.next_user_id = committed.next_user_id

        _replace_mapping(self._state.roles_by_id, committed.roles_by_id)
        _replace_mapping(self._state.role_id_by_name, committed.role_id_by_name)
        _replace_mapping(self._state.role_ids_by_user_id, committed.role_ids_by_user_id)

        _replace_mapping(self._state.channels_by_id, committed.channels_by_id)
        _replace_mapping(self._state.channel_id_by_name, committed.channel_id_by_name)
        _replace_mapping(
            self._state.channel_overrides_by_channel_id,
            committed.channel_overrides_by_channel_id,
        )
        self._state.next_channel_id = committed.next_channel_id
        _replace_mapping(
            self._state.channel_messages_by_id,
            committed.channel_messages_by_id,
        )
        _replace_mapping(
            self._state.private_messages_by_id,
            committed.private_messages_by_id,
        )
        self._state.next_channel_message_id = committed.next_channel_message_id
        self._state.next_private_message_id = committed.next_private_message_id
        _replace_mapping(
            self._state.friend_relationships_by_key,
            committed.friend_relationships_by_key,
        )

        self._commit_score_state(committed)
        _replace_mapping(self._state.personal_bests_by_id, committed.personal_bests_by_id)
        _replace_mapping(
            self._state.personal_best_id_by_scope,
            committed.personal_best_id_by_scope,
        )
        self._state.next_personal_best_id = committed.next_personal_best_id
        self._commit_beatmap_leaderboard_state(committed)
        self._commit_beatmap_performance_best_state(committed)

        _replace_mapping(self._state.submissions_by_id, committed.submissions_by_id)
        _replace_mapping(
            self._state.submission_id_by_fingerprint,
            committed.submission_id_by_fingerprint,
        )
        self._state.next_submission_id = committed.next_submission_id

        self._commit_replay_state(committed)

        _replace_mapping(self._state.blobs_by_id, committed.blobs_by_id)
        _replace_mapping(self._state.blob_id_by_sha256, committed.blob_id_by_sha256)
        self._state.next_blob_id = committed.next_blob_id

        _replace_mapping(self._state.beatmapsets_by_id, committed.beatmapsets_by_id)
        _replace_mapping(self._state.beatmaps_by_id, committed.beatmaps_by_id)
        _replace_mapping(self._state.beatmap_id_by_checksum, committed.beatmap_id_by_checksum)
        _replace_mapping(
            self._state.beatmap_submission_counts_by_id,
            committed.beatmap_submission_counts_by_id,
        )
        _replace_mapping(self._state.attachments_by_key, committed.attachments_by_key)
        _replace_mapping(
            self._state.attachment_keys_by_beatmap_id,
            committed.attachment_keys_by_beatmap_id,
        )
        _replace_mapping(self._state.fetch_states_by_target, committed.fetch_states_by_target)

        _replace_mapping(
            self._state.performance_calculations_by_id,
            committed.performance_calculations_by_id,
        )
        _replace_mapping(
            self._state.current_performance_calculation_id_by_score_id,
            committed.current_performance_calculation_id_by_score_id,
        )
        _replace_mapping(
            self._state.replacement_performance_calculation_id_by_score_id,
            committed.replacement_performance_calculation_id_by_score_id,
        )
        _replace_mapping(
            self._state.performance_claims_by_calculation_id,
            committed.performance_claims_by_calculation_id,
        )
        self._state.next_performance_calculation_id = committed.next_performance_calculation_id

        _replace_mapping(
            self._state.performance_recalculation_batches_by_id,
            committed.performance_recalculation_batches_by_id,
        )
        _replace_mapping(
            self._state.performance_recalculation_work_items_by_id,
            committed.performance_recalculation_work_items_by_id,
        )
        _replace_mapping(
            self._state.performance_recalculation_work_item_ids_by_batch_id,
            committed.performance_recalculation_work_item_ids_by_batch_id,
        )
        self._state.next_performance_recalculation_batch_id = (
            committed.next_performance_recalculation_batch_id
        )
        self._state.next_performance_recalculation_work_item_id = (
            committed.next_performance_recalculation_work_item_id
        )

    def _commit_replay_state(
        self,
        committed: InMemoryCommandRepositoryState,
    ) -> None:
        """Replay と checksum 索引の committed state を置き換える.

        Args:
            committed (InMemoryCommandRepositoryState): 反映元となる clone 済み UoW state.

        Returns:
            None: Replay 索引と Replay ID の採番 counter を更新する.

        Notes:
            replay mapping の container identity と更新順を維持する. 他の state field はこの helper
            では変更しない.
        """
        _replace_mapping(self._state.replays_by_id, committed.replays_by_id)
        _replace_mapping(self._state.replay_id_by_checksum, committed.replay_id_by_checksum)
        self._state.next_replay_id = committed.next_replay_id

    def _commit_beatmap_leaderboard_state(
        self,
        committed: InMemoryCommandRepositoryState,
    ) -> None:
        """Beatmap leaderboard projection の committed state を置き換える.

        Args:
            committed (InMemoryCommandRepositoryState): 反映元となる clone 済み UoW state.

        Returns:
            None: leaderboard user best の索引と採番 counter を更新する.

        Notes:
            factory の他の state field はこの helper では変更しない.
        """
        _replace_mapping(
            self._state.beatmap_leaderboard_user_bests_by_id,
            committed.beatmap_leaderboard_user_bests_by_id,
        )
        _replace_mapping(
            self._state.beatmap_leaderboard_user_best_id_by_scope,
            committed.beatmap_leaderboard_user_best_id_by_scope,
        )
        self._state.next_beatmap_leaderboard_user_best_id = (
            committed.next_beatmap_leaderboard_user_best_id
        )

    def _commit_beatmap_performance_best_state(
        self,
        committed: InMemoryCommandRepositoryState,
    ) -> None:
        """Beatmap performance best と current stats projection を反映する.

        Args:
            committed (InMemoryCommandRepositoryState): 反映元となる clone 済み UoW state.

        Returns:
            None: performance best の索引と採番 counter, current stats projection を更新する.

        Notes:
            factory の他の state field はこの helper では変更しない.
        """
        _replace_mapping(
            self._state.beatmap_performance_bests_by_id,
            committed.beatmap_performance_bests_by_id,
        )
        _replace_mapping(
            self._state.beatmap_performance_best_id_by_scope,
            committed.beatmap_performance_best_id_by_scope,
        )
        self._state.next_beatmap_performance_best_id = committed.next_beatmap_performance_best_id
        _replace_mapping(
            self._state.current_user_stats_by_scope,
            committed.current_user_stats_by_scope,
        )

    def _commit_score_state(
        self,
        committed: InMemoryCommandRepositoryState,
    ) -> None:
        """Score と leaderboard eligibility の committed state を置き換える.

        Args:
            committed (InMemoryCommandRepositoryState): 反映元となる clone 済み UoW state.

        Returns:
            None: score 索引, online checksum 索引, eligibility, 採番 counter を更新する.

        Notes:
            factory の他の state field はこの helper では変更しない.
        """
        _replace_mapping(self._state.scores_by_id, committed.scores_by_id)
        _replace_mapping(
            self._state.score_id_by_online_checksum,
            committed.score_id_by_online_checksum,
        )
        _replace_mapping(
            self._state.score_leaderboard_eligibility_by_id,
            committed.score_leaderboard_eligibility_by_id,
        )
        self._state.next_score_id = committed.next_score_id

    def seed_roles(self, roles: list[Role]) -> None:
        """Factory の committed state に Role を直接 seed するテスト helper.

        Args:
            roles (list[Role]): ID と name の索引に追加する Role.

        Returns:
            None: roles_by_id と role_id_by_name を直接更新する.

        Notes:
            UoW を開かず commit/rollback を経由しない. 同じ ID または name は後の Role で
            上書きされる.
        """
        for role in roles:
            self._state.roles_by_id[role.id] = role
            self._state.role_id_by_name[role.name] = role.id


class InMemoryUnitOfWork:
    """Commit/rollback semantics を持つ in-memory command transaction boundary.

    Attributes:
        users (InMemoryUserCommandRepository): User command repository.
        roles (InMemoryRoleCommandRepository): Role command repository.
        channels (InMemoryChannelCommandRepository): Channel command repository.
        chat (InMemoryChatCommandRepository): Chat command repository.
        friends (InMemoryFriendRelationshipCommandRepository): Friend command repository.
        scores (InMemoryScoreCommandRepository): Score command repository.
        personal_bests (InMemoryPersonalBestCommandRepository): Personal Best command repository.
        score_performance (InMemoryScorePerformanceCommandRepository): Performance command
            repository.
        submissions (InMemoryScoreSubmissionCommandRepository): Submission command repository.
        replays (InMemoryReplayCommandRepository): Replay command repository.
        blobs (InMemoryBlobCommandRepository): Blob command repository.
        beatmaps (InMemoryBeatmapCommandRepository): Beatmap command repository.
        beatmap_leaderboards (InMemoryBeatmapLeaderboardCommandRepository): Leaderboard command
            repository.
        beatmap_performance_bests (InMemoryBeatmapPerformanceBestCommandRepository): Performance
            best command repository.
        current_user_stats (InMemoryCurrentUserStatsCommandRepository): Current UserStats command
            repository.

    Notes:
        Repository は UoW の作業 snapshot を共有する. commit() は factory の committed state へ
        即時に publish する. 後続の例外または rollback は local state と repository の束縛だけを
        最新 snapshot に戻し, publish 済みの factory state は取り消さない.
    """

    users: InMemoryUserCommandRepository
    roles: InMemoryRoleCommandRepository
    channels: InMemoryChannelCommandRepository
    chat: InMemoryChatCommandRepository
    friends: InMemoryFriendRelationshipCommandRepository
    scores: InMemoryScoreCommandRepository
    personal_bests: InMemoryPersonalBestCommandRepository
    score_performance: InMemoryScorePerformanceCommandRepository
    submissions: InMemoryScoreSubmissionCommandRepository
    replays: InMemoryReplayCommandRepository
    blobs: InMemoryBlobCommandRepository
    beatmaps: InMemoryBeatmapCommandRepository
    beatmap_leaderboards: InMemoryBeatmapLeaderboardCommandRepository
    beatmap_performance_bests: InMemoryBeatmapPerformanceBestCommandRepository
    current_user_stats: InMemoryCurrentUserStatsCommandRepository

    def __init__(self, factory: InMemoryUnitOfWorkFactory) -> None:
        """Factory snapshot を作業 state として UoW を初期化する.

        Args:
            factory (InMemoryUnitOfWorkFactory): snapshot と commit 先を提供する factory.

        Returns:
            None: 未 commit の UoW と command repository 群を構築する.

        Notes:
            初期 state は factory.snapshot() の clone であり, factory の committed state を直接
            変更しない.
        """
        self._factory: InMemoryUnitOfWorkFactory = factory
        self._state: InMemoryCommandRepositoryState = factory.snapshot()
        self._committed: bool = False
        self._bind_repositories()

    async def __aenter__(self) -> Self:
        """この UoW 自身を非同期 context の値として返す.

        Returns:
            Self: 初期化済みのこの UoW.

        Notes:
            entry 時には state を commit も rollback も行わない.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """未 commit または例外終了の UoW を rollback する.

        Args:
            exc_type (type[BaseException] | None): context 内で発生した例外の型. 例外がなければ
                None.
            _exc (BaseException | None): context 内で発生した例外 instance. 本実装では参照しない.
            _traceback (TracebackType | None): 例外 traceback. 本実装では参照しない.

        Returns:
            None: 例外を抑制せず, 必要な rollback だけを行う.

        Notes:
            例外がある場合または commit 未実行の場合は rollback する. commit 後に例外が発生した
            場合も rollback は呼ばれるが, factory へ publish 済みの state は取り消さない. 例外が
            なく commit 済みの場合は state を変更しない.
        """
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        """作業 state を factory の committed state に反映する.

        Returns:
            None: factory.commit_state() を呼び, この UoW を commit 済みにする.

        Notes:
            factory.commit_state() はこの呼び出し中に state を即時 publish する. commit 後に
            context 内で例外が発生すると __aexit__ は rollback するが, publish 済みの factory
            state は取り消さない.
        """
        self._factory.commit_state(self._state)
        self._committed = True

    async def rollback(self) -> None:
        """作業 state を最新 committed snapshot に戻して repository を再束縛する.

        Returns:
            None: 未 commit 状態に戻し, 各 command repository の操作対象を新しい state にする.

        Notes:
            factory の committed state は変更しない. commit 後の例外で呼ばれても publish 済みの
            state は取り消さない. 既存の repository instance は新しい state を参照し続けないため,
            再束縛後の attribute を使用する必要がある.
        """
        self._state = self._factory.snapshot()
        self._committed = False
        self._bind_repositories()

    def _bind_repositories(self) -> None:
        """現在の作業 state を各 command repository に束縛する.

        Returns:
            None: UoW の repository attribute を新しい repository instance に置き換える.

        Notes:
            この helper は state を commit も rollback も行わない. __init__ と rollback からのみ
            呼ばれる.
        """
        self.users = InMemoryUserCommandRepository(self._state)
        self.roles = InMemoryRoleCommandRepository(self._state)
        self.channels = InMemoryChannelCommandRepository(self._state)
        self.chat = InMemoryChatCommandRepository(self._state)
        self.friends = InMemoryFriendRelationshipCommandRepository(self._state)
        self.scores = InMemoryScoreCommandRepository(self._state)
        self.personal_bests = InMemoryPersonalBestCommandRepository(self._state)
        self.score_performance = InMemoryScorePerformanceCommandRepository(self._state)
        self.submissions = InMemoryScoreSubmissionCommandRepository(self._state)
        self.replays = InMemoryReplayCommandRepository(self._state)
        self.blobs = InMemoryBlobCommandRepository(self._state)
        self.beatmaps = InMemoryBeatmapCommandRepository(self._state)
        self.beatmap_leaderboards = InMemoryBeatmapLeaderboardCommandRepository(self._state)
        self.beatmap_performance_bests = InMemoryBeatmapPerformanceBestCommandRepository(
            self._state
        )
        self.current_user_stats = InMemoryCurrentUserStatsCommandRepository(self._state)
