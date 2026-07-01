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
    ScorePayloadParser,
    ScoreSubmissionAuthorizer,
    SubmissionOutcome,
    SubmissionResult,
    generate_submission_fingerprint,
    generate_submission_request_hash,
    hash_submission_metadata,
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
    "ParsedSubmissionInput",
    "ProcessScoreSubmissionUseCase",
    "RebuildBeatmapLeaderboardsForBeatmapsetCommand",
    "RebuildBeatmapLeaderboardsForBeatmapsetUseCase",
    "RebuildBeatmapLeaderboardsForUserCommand",
    "RebuildBeatmapLeaderboardsForUserUseCase",
    "RebuildBeatmapLeaderboardsResult",
    "ScoreAuthorizationService",
    "ScorePayloadParser",
    "ScoreSubmissionAuthorizer",
    "SubmissionOutcome",
    "SubmissionResult",
    "SubmitScoreCommand",
    "SubmitScoreCommandOutcome",
    "SubmitScoreCommandResult",
    "SubmitScoreUseCase",
    "build_current_user_stats_projection",
    "generate_submission_fingerprint",
    "generate_submission_request_hash",
    "hash_submission_metadata",
    "replace_current_user_stats_projection",
]
