"""Score command use-case package."""

from osu_server.services.commands.scores.authorization import (
    AuthorizationContext,
    ScoreAuthorizationService,
)
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserCommand,
    RebuildBeatmapLeaderboardsForUserUseCase,
    RebuildBeatmapLeaderboardsResult,
)
from osu_server.services.commands.scores.process_submission import (
    BeatmapRankDelta,
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    ScoreSubmissionAuthorizer,
    SubmissionOutcome,
    SubmissionResult,
    generate_submission_fingerprint,
)
from osu_server.services.commands.scores.replay_download_accounting import (
    LatestActivityAccountingOutcome,
    ReplayDownloadAccountingInput,
    ReplayDownloadAccountingResult,
    ReplayDownloadAccountingUseCase,
    ReplayViewAccountingOutcome,
)
from osu_server.services.commands.scores.submit_score import (
    SubmitScoreCommand,
    SubmitScoreCommandOutcome,
    SubmitScoreCommandResult,
    SubmitScoreUseCase,
)
from osu_server.services.commands.scores.user_stats_projection import (
    build_current_user_stats_projection,
    replace_current_user_stats_projection,
)

__all__ = [
    "AuthorizationContext",
    "BeatmapRankDelta",
    "LatestActivityAccountingOutcome",
    "ParsedSubmissionInput",
    "ProcessScoreSubmissionUseCase",
    "RebuildBeatmapLeaderboardsForBeatmapsetCommand",
    "RebuildBeatmapLeaderboardsForBeatmapsetUseCase",
    "RebuildBeatmapLeaderboardsForUserCommand",
    "RebuildBeatmapLeaderboardsForUserUseCase",
    "RebuildBeatmapLeaderboardsResult",
    "ReplayDownloadAccountingInput",
    "ReplayDownloadAccountingResult",
    "ReplayDownloadAccountingUseCase",
    "ReplayViewAccountingOutcome",
    "ScoreAuthorizationService",
    "ScoreSubmissionAuthorizer",
    "SubmissionOutcome",
    "SubmissionResult",
    "SubmitScoreCommand",
    "SubmitScoreCommandOutcome",
    "SubmitScoreCommandResult",
    "SubmitScoreUseCase",
    "build_current_user_stats_projection",
    "generate_submission_fingerprint",
    "replace_current_user_stats_projection",
]
