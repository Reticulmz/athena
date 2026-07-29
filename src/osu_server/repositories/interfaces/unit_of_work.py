"""Command-side durable transaction を所有する Unit of Work contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from osu_server.repositories.interfaces.commands import (
        BeatmapCommandRepository,
        BeatmapLeaderboardCommandRepository,
        BeatmapPerformanceBestCommandRepository,
        BlobCommandRepository,
        ChannelCommandRepository,
        ChatCommandRepository,
        CurrentUserStatsCommandRepository,
        FriendRelationshipCommandRepository,
        PersonalBestCommandRepository,
        ReplayCommandRepository,
        RoleCommandRepository,
        ScoreCommandRepository,
        ScorePerformanceCommandRepository,
        ScoreSubmissionCommandRepository,
        UserCommandRepository,
    )


class UnitOfWork(Protocol):
    """Command repository 群の durable transaction boundary を定義する.

    Attributes:
        users (UserCommandRepository): User command persistence port.
        roles (RoleCommandRepository): Role assignment command persistence port.
        channels (ChannelCommandRepository): Channel command persistence port.
        chat (ChatCommandRepository): Chat message command persistence port.
        friends (FriendRelationshipCommandRepository): Friend relationship command port.
        scores (ScoreCommandRepository): Score command persistence port.
        personal_bests (PersonalBestCommandRepository): Personal best command port.
        score_performance (ScorePerformanceCommandRepository): Performance command port.
        submissions (ScoreSubmissionCommandRepository): Score submission command port.
        replays (ReplayCommandRepository): Replay command persistence port.
        blobs (BlobCommandRepository): Blob metadata command persistence port.
        beatmaps (BeatmapCommandRepository): Beatmap command persistence port.
        beatmap_leaderboards (BeatmapLeaderboardCommandRepository): Leaderboard command port.
        beatmap_performance_bests (BeatmapPerformanceBestCommandRepository): Beatmap PP port.
        current_user_stats (CurrentUserStatsCommandRepository): Current stats command port.

    Notes:
        実装が low-level persistence transaction を所有する. この boundary から得た command
        repository は独自に commit/rollback してはならない. Query repository と SessionStore は
        この Unit of Work に含まれず transaction を共有しない.
    """

    users: UserCommandRepository
    roles: RoleCommandRepository
    channels: ChannelCommandRepository
    chat: ChatCommandRepository
    friends: FriendRelationshipCommandRepository
    scores: ScoreCommandRepository
    personal_bests: PersonalBestCommandRepository
    score_performance: ScorePerformanceCommandRepository
    submissions: ScoreSubmissionCommandRepository
    replays: ReplayCommandRepository
    blobs: BlobCommandRepository
    beatmaps: BeatmapCommandRepository
    beatmap_leaderboards: BeatmapLeaderboardCommandRepository
    beatmap_performance_bests: BeatmapPerformanceBestCommandRepository
    current_user_stats: CurrentUserStatsCommandRepository

    async def commit(self) -> None:
        """この Unit of Work 内の command changes を一つの durable outcome として commit する.

        Returns:
            None: Commit が完了したことを表す.

        Notes:
            Factory が開いた active scope 内で呼び出す. Query repository の read operation と
            SessionStore の volatile update は commit 対象ではない.
        """
        ...

    async def rollback(self) -> None:
        """この Unit of Work 内の未 commit command changes を rollback する.

        Returns:
            None: 未 commit change の rollback 完了を表す.

        Notes:
            Factory が開いた active scope 内で呼び出す. Query repository の read operation と
            SessionStore の volatile update は rollback 対象ではない.
        """
        ...


class UnitOfWorkFactory(Protocol):
    """Command Unit of Work scope を開く factory contract を定義する.

    Notes:
        返される context manager が command transaction の lifecycle を所有する. Query
        repository はこの factory を使わず read-only operation ごとに独立して扱う.
    """

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        """一つの command transaction 用 async context manager を返す.

        Returns:
            AbstractAsyncContextManager[UnitOfWork]: `async with` で使用する Unit of Work scope.

        Notes:
            Context を exception 付きで終了した場合または `commit()` されていない場合の
            rollback と resource cleanup は実装が管理する.
        """
        ...
